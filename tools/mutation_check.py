"""mutation_check.py - targeted mutation testing for the gates that must not rot.

Why this exists (PLAN.md Phase 5 task 6)
----------------------------------------
Coverage says a line ran; it does not say the line's *decision* was ever
observed to matter.  A gate can be 100% covered and still be useless: the
assertion may sit on the wrong field, the failing branch may never be taken,
or the test may pass for a reason unrelated to the code under test.  That is
not hypothetical here - `tests/test_tyrano_pipeline.py` patched a name through
the retired `config` facade and only stayed green because ffmpeg genuinely was
not installed on the machine (see docs/experience-misc.md section 11.4).

Mutation testing is the countermeasure: make one deliberate, *semantic* change
that removes the guard, and require the suite to notice.  A mutation that
survives means the guard is decoration.

Why not `mutmut`: it refuses to run on Windows ("To run mutmut on Windows,
please use the WSL"), and running WSL-native tools over a Windows-side tree is
exactly what the cross-system CRITICAL rule forbids (ADR-0002).  This tool
therefore uses the pattern already proven in this repo
(`tests/test_wheel_contents.py::_copy_tree_to`): build in a temporary copy,
never in place, and run real pytest against that copy.

Selectors are **exact node ids**, not `-k` expressions.  A substring guess is
how the first version of this table reported "the attributed selector matches
no test" for `-k gate_codes` while the real test was called
`test_gate_control_codes_fails`: a selector that matches nothing would
otherwise let a mutation look detected for free, so the harness treats "no
tests collected" as an error rather than a pass.

The table is deliberately small and hand-picked.  Random mutation farms
generate thousands of equivalent mutants ("is this percentage rounded up or
down") whose survival means nothing; the six risk sites PLAN.md names are worth
more than a score.  Each entry records *why* that single change is the one that
matters, and which test is responsible for noticing it.

Usage
-----
    # Show the table without running anything.
    python tools/mutation_check.py --list

    # Prove every mutation in the table is detected (the gate).
    python tools/mutation_check.py

    # One entry, for iterating on a table edit.
    python tools/mutation_check.py --only coverage-gate

Exit code is 0 only when every mutation was killed by a test that passes on the
unmutated copy.  That "passes on the unmutated copy" half matters: a selector
that is already red would otherwise let a mutation look detected for free.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Annotated, NamedTuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(REPO_ROOT)

import typer  # noqa: E402

from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("mutation_check")

#: Seconds allowed for one pytest invocation inside the copy.
DEFAULT_TIMEOUT = 900

#: What never needs to travel into the mutation copy.  Same set as the wheel
#: build uses, except that `tests/` stays: the suite is the detector.
COPY_IGNORE = shutil.ignore_patterns(
    "build", "dist", "*.egg-info", "__pycache__", ".venv", ".git",
    ".pytest_cache", ".ruff_cache", ".tmp", ".tools", ".pi", "docs",
    "tmp", "work", ".private", ".asset", "PLAN.md",
    # Hypothesis' example database: not source, and copying it would carry
    # this checkout's cached counterexamples into the mutation tree, which is
    # exactly the sort of environment-dependent input the control run must
    # not inherit.
    ".hypothesis")


class Mutation(NamedTuple):
    """One deliberate removal of a guard, and the test that must notice it.

    `find` must occur exactly once in `path`; the harness refuses an ambiguous
    anchor rather than mutating the first hit, because a silently wrong edit
    would report "survived" for the mutation that was never made.
    """

    # `selector` is an exact node id; `criteria` is the readable form of the
    # same thing (empty means "the whole file").
    mid: str
    site: str
    path: str
    find: str
    replace: str
    selector: tuple
    why: str
    criteria: str = ""


MUTATIONS = (
    Mutation(
        mid="coverage-gate",
        site="translation coverage gate",
        path="translation/rawlib.py",
        find='"ok": not missing,',
        replace='"ok": True,',
        selector=("tests/test_translation_v2.py::test_gate_coverage_fails",),
        why="Unaffected keys must fail the gate; otherwise bake proceeds with "
            "untranslated text and the delivered build is half Japanese.",
        criteria="gate coverage",
    ),
    Mutation(
        mid="control-code-gate",
        site="translation control-code gate",
        path="translation/rawlib.py",
        find='"ok": not mismatch,',
        replace='"ok": True,',
        selector=("tests/test_translation_v2.py::test_gate_control_codes_fails",),
        why="A dropped or reordered escape code is invisible in the output "
            "text but breaks the engine; the gate is the only thing that sees "
            "it before bake.",
        criteria="gate control codes",
    ),
    Mutation(
        mid="kana-gate",
        site="translation kana-residue gate",
        path="translation/rawlib.py",
        find='"ok": not residue,',
        replace='"ok": True,',
        selector=("tests/test_translation_v2.py::test_gate_kana_residue_and_allowlist",
                  "tests/test_translation_v2.py::test_gate_flags_kana_in_name_box"),
        why="Untranslated Japanese left in a value is the single most common "
            "silent defect of a long translation run.",
        criteria="kana residue",
    ),
    Mutation(
        mid="line-break-gate",
        site="translation line-break gate",
        path="translation/rawlib.py",
        find='"ok": not mismatched,',
        replace='"ok": True,',
        selector=("tests/test_translation_v2.py::test_gate_line_breaks_fails_on_truncated_multiline",),
        why="A value with fewer newlines than its source is a truncated "
            "translation; this is how 42 skill descriptions lost a line.",
        criteria="line breaks",
    ),
    Mutation(
        mid="batch-rejection",
        site="translation batch all-or-nothing",
        path="translation/rawlib.py",
        find='    if problems:\n        return {"added": 0',
        replace='    if False:\n        return {"added": 0',
        selector=("tests/test_translation_v2.py::test_append_batch_validates_before_writing",
                  "tests/test_translation_v2.py::test_append_rejects_truncated_multiline_batch"),
        why="One bad block must reject the whole batch; a partially appended "
            "batch is hard to unwind because the library is append-only.",
        criteria="batch validation",
    ),
    Mutation(
        mid="archive-integrity",
        site="archive integrity verdict",
        path="rpgmaker/archive.py",
        find="    if bad:\n        log.error",
        replace="    if False:\n        log.error",
        selector=("tests/test_error_recovery.py::TestCorruptedInput::test_a_corrupt_archive_content_is_reported_false",),
        why="A corrupt archive reported as verified ships a broken download; "
            "callers branch on this boolean.",
        criteria="corrupt archive",
    ),
    Mutation(
        mid="same-side-refusal",
        site="cross-system write refusal",
        path="rpgmaker/platform.py",
        find="    report.require(what)\n    return owned",
        replace="    # Mutant: processor ownership check removed.\n    return owned",
        selector=("tests/test_compress.py::TestArchiveModule::test_extract_refuses_a_windows_side_destination",),
        why="This is the AGENTS.md CRITICAL rule: a WSL-native process writing "
            "a /mnt/* tree once caused host display corruption.",
        criteria="same-side refusal",
    ),
    Mutation(
        mid="decrypt-flag-condition",
        site="decryption flag clearing gated on the easy case",
        path="rpgmaker/decrypt.py",
        find='    if skipped:\n        log.warning("complex encryption',
        replace='    if False:\n        log.warning("complex encryption',
        selector=("tests/test_decrypt.py::TestSystemJson::test_clear_encryption_flags",
                  "tests/test_decrypt.py::TestTreeDecrypt::test_complex_kept_flags_kept",),
        why="Clearing the flags on a complex-encrypted game makes the engine "
            "read still-encrypted files as plaintext and the game stops "
            "starting.",
        criteria="complex encryption",
    ),
    Mutation(
        mid="verify-flag-detection",
        site="build verification: leftover encryption flags",
        path="rpgmaker/verify.py",
        find='    if s.get("hasEncryptedImages") or s.get("hasEncryptedAudio"):',
        replace="    if False:",
        selector=("tests/test_verify.py::TestSystemFlags::test_flags_set",),
        why="verify is the last automated gate before delivery; a flag check "
            "that cannot fail is worse than no check.",
        criteria="system flags",
    ),
    Mutation(
        mid="verify-source-baseline",
        site="build verification: source-vs-build reference comparison",
        path="rpgmaker/verify.py",
        find="        if _source_has_audio(source_dir, folder, name):",
        replace="        if False:",
        selector=("tests/test_verify.py::TestAudioRefs::test_missing_is_failure",
                  "tests/test_verify.py::TestAudioRefs::test_missing_in_source_too_is_warning"),
        why="The whole value of `--source` is separating a real build failure "
            "from a pre-existing quirk; inverting the comparison swaps which "
            "one is reported.",
        criteria="audio reference baseline",
    ),
)

BY_ID = collections.OrderedDict((m.mid, m) for m in MUTATIONS)


class Outcome(NamedTuple):
    mid: str
    status: str          # killed | survived | error
    detail: str
    seconds: float


def apply_mutation(root, mutation):
    """Write the mutated source into `root`; raise on an ambiguous anchor."""
    path = os.path.join(root, mutation.path)
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    count = text.count(mutation.find)
    if count != 1:
        raise LookupError(
            "%s: anchor occurs %d times in %s, expected exactly 1 - the table "
            "is stale (refusing to mutate the wrong site)"
            % (mutation.mid, count, mutation.path))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text.replace(mutation.find, mutation.replace))


def pytest_argv(mutation):
    return [sys.executable, "-m", "pytest", *mutation.selector,
            "-q", "-n", "0", "--no-header", "-p", "no:cacheprovider"]


def run_pytest(root, mutation, timeout):
    """Run the attributed selector inside `root`; return (exit code, output)."""
    env = dict(os.environ)
    # The copy must be imported, not the checkout the harness is running from.
    env.pop("PYTHONPATH", None)
    try:
        proc = subprocess.run(
            pytest_argv(mutation), cwd=root, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timed out after %ds" % timeout
    return proc.returncode, proc.stdout


def tail(text, lines=4):
    rows = [row for row in (text or "").strip().splitlines() if row.strip()]
    return " | ".join(rows[-lines:])


def check(repo_root=REPO_ROOT, mutations=MUTATIONS, timeout=DEFAULT_TIMEOUT,
          keep=False):
    """Run every mutation in a fresh copy; yield `Outcome` per mutation."""
    started = time.time()
    workdir = tempfile.mkdtemp(prefix="gt-mutation-")
    try:
        root = os.path.join(workdir, "GameTranslation")
        log.info("copying the source into %s", root)
        shutil.copytree(repo_root, root, ignore=COPY_IGNORE)
        log.debug("copy ready in %.2fs", time.time() - started)

        # The unmutated run is the control: a selector that is already red
        # would otherwise let a surviving mutation look killed.
        controls = collections.OrderedDict()
        for mutation in mutations:
            if mutation.selector in controls:
                continue
            at = time.time()
            code, out = run_pytest(root, mutation, timeout)
            controls[mutation.selector] = (code, out)
            log.info("control %s -> %s (%.1fs)", " ".join(mutation.selector),
                     code, time.time() - at)
            if code not in (0, 5):
                yield Outcome(mutation.mid, "error",
                              "the attributed selector fails before any "
                              f"mutation: exit {code}; {tail(out)}",
                              time.time() - at)
                return
            if code == 5:
                yield Outcome(mutation.mid, "error",
                              "the attributed selector matches no test "
                              "({}) - the table is stale".format(" ".join(mutation.selector)),
                              time.time() - at)
                return

        for mutation in mutations:
            at = time.time()
            try:
                apply_mutation(root, mutation)
            except LookupError as exc:
                yield Outcome(mutation.mid, "error", str(exc),
                              time.time() - at)
                continue
            code, out = run_pytest(root, mutation, timeout)
            elapsed = time.time() - at
            if code is None:
                status, detail = "error", tail(out)
            elif code == 0:
                status, detail = "survived", (
                    "every attributed test still passed with the guard "
                    "removed: {}".format(" ".join(mutation.selector)))
            else:
                status, detail = "killed", tail(out)
            log.info("%-24s %-8s (%.1fs)", mutation.mid, status, elapsed)
            # Restore the anchor so the next mutation starts from clean source
            # (two entries may touch one file).
            if not _restore(root, mutation):
                yield Outcome(mutation.mid, "error",
                              f"cannot restore {mutation.path} after mutating it", elapsed)
                return
            yield Outcome(mutation.mid, status, detail, elapsed)
    finally:
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            log.info("copy kept at %s", workdir)


def _restore(root, mutation):
    path = os.path.join(root, mutation.path)
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        if mutation.find in text:
            return True
        if mutation.replace not in text:
            return False
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text.replace(mutation.replace, mutation.find))
        return True
    except OSError as exc:
        log.error("cannot restore %s: %s", mutation.path, exc)
        return False


def as_json(outcomes):
    rows = [{"id": o.mid, "status": o.status, "detail": o.detail,
             "seconds": round(o.seconds, 2)} for o in outcomes]
    killed = sum(1 for row in rows if row["status"] == "killed")
    return {"mutations": rows, "killed": killed, "total": len(rows),
            "ok": killed == len(rows) and bool(rows)}


def render(outcomes):
    """Human-readable lines; the caller decides where they go."""
    lines = []
    for outcome in outcomes:
        mutation = BY_ID.get(outcome.mid)
        label = mutation.site if mutation else outcome.mid
        lines.append("%-9s %-22s %s" % (outcome.status.upper(), outcome.mid,
                                        label))
        if outcome.status != "killed":
            lines.append(f"          {outcome.detail}")
    killed = sum(1 for o in outcomes if o.status == "killed")
    lines.append("%d/%d mutations detected" % (killed, len(outcomes)))
    return "\n".join(lines)


def cmd(
    only: Annotated[str | None, typer.Option(
        "--only", help="comma-separated mutation ids to run")] = None,
    list_only: Annotated[bool, typer.Option(
        "--list", help="print the table and exit")] = False,
    as_json_flag: Annotated[bool, typer.Option(
        "--json", help="machine-readable structured output")] = False,
    keep: Annotated[bool, typer.Option(
        "--keep", help="keep the mutation copy for inspection")] = False,
    timeout: Annotated[int, typer.Option(
        "--timeout", help="seconds allowed per pytest run")] = DEFAULT_TIMEOUT,
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Prove the named gates are really detected by the tests that guard them."""
    if list_only:
        for mutation in MUTATIONS:
            print("%-24s %-24s %s" % (mutation.mid, mutation.path,
                                      mutation.site))
            print(f"    why: {mutation.why}")
            print("    test: pytest {}".format(" ".join(mutation.selector)))
        return 0

    selected = MUTATIONS
    if only:
        wanted = [part.strip() for part in only.split(",") if part.strip()]
        unknown = [mid for mid in wanted if mid not in BY_ID]
        if unknown:
            return cliutil.fail("unknown mutation id(s): {} (see --list)".format(", ".join(unknown)))
        selected = tuple(BY_ID[mid] for mid in wanted)

    outcomes = list(check(mutations=selected, timeout=timeout, keep=keep))
    report = as_json(outcomes)
    if as_json_flag:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(outcomes), file=sys.stderr if quiet else sys.stdout)
    if not report["ok"]:
        bad = [row["id"] for row in report["mutations"]
               if row["status"] != "killed"]
        return cliutil.fail("mutation(s) not detected: {}".format(", ".join(bad)))
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
