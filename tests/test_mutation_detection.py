#!/usr/bin/env python3
"""Gate: every entry in the mutation table is really detected (PLAN 5 task 6).

`tools/mutation_check.py` holds a small, hand-picked table of deliberate
guard removals.  Two things can make that table lie, and this file guards both:

* **A stale anchor.** The mutation is applied by exact string match, so a
  refactor that rewrites the guard silently turns the entry into a no-op.  The
  harness already refuses an ambiguous anchor; this file additionally pins the
  anchor as a claim about the file, so a rename shows up as a test failure
  instead of a mutation that reports "killed" for the wrong reason.
* **An entry nobody runs.** The table is only worth its runtime if it is wired
  into a gate.  The expensive part (a copy plus 1-2 pytest runs per entry,
  measured ~15-25 s total) runs under the `slow` marker; the structural half
  here runs in the fast layer.

The mutation RUNS live in `tests/test_mutation_detection.py`, class
`TestMutationsAreDetected`, marked `slow` - two layers because the table's
shape is cheap to check and the proof is not.
"""
import os
import shutil
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools import mutation_check as mc  # noqa: E402

#: The six risk sites PLAN.md Phase 5 task 6 names, and the mutation that
#: covers each.  Kept as an explicit list so deleting a mutation is a
#: deliberate edit to this file rather than a silent shrink of the table.
REQUIRED_SITES = {
    "translation control codes": "control-code-gate",
    "translation line breaks": "line-break-gate",
    "translation coverage": "coverage-gate",
    "archive integrity": "archive-integrity",
    "windows/wsl same-side refusal": "same-side-refusal",
    "decryption flag": "decrypt-flag-condition",
    "resource reference verification": "verify-source-baseline",
}


class TestTableShape:
    def test_ids_are_unique(self):
        ids = [m.mid for m in mc.MUTATIONS]
        assert len(ids) == len(set(ids))

    def test_every_named_risk_site_has_a_mutation(self):
        have = {m.mid for m in mc.MUTATIONS}
        missing = {site: mid for site, mid in REQUIRED_SITES.items()
                   if mid not in have}
        assert not missing, (
            "PLAN Phase 5 task 6 names these risk sites and the table no "
            f"longer covers them: {missing}")

    def test_every_mutation_says_why_it_matters(self):
        thin = [m.mid for m in mc.MUTATIONS if len(m.why) < 40]
        assert not thin, f"these entries do not explain the stake: {thin}"

    def test_every_mutation_changes_behaviour_not_only_text(self):
        """A no-op edit (`x == 1` -> `x == 1`) would report 'survived' forever."""
        same = [m.mid for m in mc.MUTATIONS if m.find == m.replace]
        assert not same
        for mutation in mc.MUTATIONS:
            assert mutation.find != mutation.replace
            assert mutation.find not in mutation.replace, (
                f"{mutation.mid}: the replacement still contains the anchor, so restoring "
                "the file cannot be distinguished from leaving it mutated")

    def test_anchors_are_unique_in_their_file(self):
        """A stale/ambiguous anchor must fail here, not silently mutate."""
        for mutation in mc.MUTATIONS:
            path = os.path.join(REPO_ROOT, mutation.path)
            assert os.path.isfile(path), (
                f"{mutation.mid}: {mutation.path} no longer exists - update or drop the entry")
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            count = text.count(mutation.find)
            assert count == 1, (
                "%s: anchor occurs %d times in %s (expected 1); the guard was "
                "refactored and the table entry is stale"
                % (mutation.mid, count, mutation.path))

    def test_selectors_point_at_real_test_files(self):
        for mutation in mc.MUTATIONS:
            for selector in mutation.selector:
                # A selector is a pytest node id ("file::Class::test"), so the
                # file part is everything before the first "::" - passing the
                # whole node id to isfile() failed on the first run.
                target = selector.split("::", 1)[0]
                assert os.path.isfile(os.path.join(REPO_ROOT, target)), (
                    f"{mutation.mid}: {target} does not exist")

    def test_only_known_ids_are_accepted_by_the_cli(self):
        assert list(mc.BY_ID) == [m.mid for m in mc.MUTATIONS]


class TestFailurePaths:
    """Every way the harness reports `error` instead of `killed`/`survived`.

    These are the paths that only fire when the table is stale, a file cannot
    be written, or a selector is wrong - i.e. exactly the situations the
    harness exists to catch, and the ones nobody exercises by accident.  All of
    them are driven against a throwaway copy so no test depends on the real
    repository being mutable.
    """

    def _copy(self, tmp_path):
        """A miniature repo: one module plus one test that imports it."""
        root = tmp_path / "repo"
        (root / "tests").mkdir(parents=True)
        (root / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "tests" / "test_mod.py").write_text(
            "from mod import VALUE\n\n\ndef test_value():\n"
            "    assert VALUE == 1\n", encoding="utf-8")
        return str(root)

    def _mutation(self, **overrides):
        entry = mc.Mutation(
            mid="probe", site="probe site", path="mod.py",
            find="VALUE = 1", replace="VALUE = 2",
            selector=("tests/test_mod.py::test_value",), why="probe")
        return entry._replace(**overrides)

    def test_a_selector_matching_no_test_is_reported(self, tmp_path):
        """Exit 5 means pytest collected nothing: the table has rotted.

        Distinguished from exit 4 (a node id that does not exist) - `check()`
        treats both as an error, but only this one is the table going stale.
        """
        root = self._copy(tmp_path)
        (tmp_path / "repo" / "tests" / "test_empty.py").write_text(
            "\"\"\"No tests collected here.\"\"\"\n", encoding="utf-8")
        mutation = self._mutation(selector=("tests/test_empty.py",))
        outcomes = list(mc.check(repo_root=root, mutations=(mutation,)))
        assert [o.status for o in outcomes] == ["error"]
        assert "matches no test" in outcomes[0].detail
        assert "the table is stale" in outcomes[0].detail
        assert mc.as_json(outcomes)["ok"] is False

    def test_an_unknown_node_id_is_reported(self, tmp_path):
        """Exit 4 (bad node id) is also an error, not a silent 'killed'."""
        root = self._copy(tmp_path)
        mutation = self._mutation(
            selector=("tests/test_mod.py::test_does_not_exist",))
        outcomes = list(mc.check(repo_root=root, mutations=(mutation,)))
        assert [o.status for o in outcomes] == ["error"]
        assert "fails before any mutation" in outcomes[0].detail

    def test_a_selector_that_already_fails_is_reported(self, tmp_path):
        """A red control would make any mutation look 'killed'.

        The control runs the selector *before* mutating, so a test that fails
        on clean source can never be offered as detection evidence.
        """
        root = self._copy(tmp_path)
        with open(os.path.join(root, "tests", "test_mod.py"), "w",
                  encoding="utf-8", newline="\n") as handle:
            handle.write("def test_value():\n    assert False\n")
        outcomes = list(mc.check(repo_root=root,
                                 mutations=(self._mutation(),)))
        assert [o.status for o in outcomes] == ["error"]
        assert "fails before any mutation" in outcomes[0].detail

    def test_an_ambiguous_anchor_is_an_error_not_a_crash(self, tmp_path):
        """A refactor that duplicates the anchor must be reported, not fatal.

        `apply_mutation` raises `LookupError` on purpose; `check()` must turn
        that into an `error` outcome so one stale entry does not abort the run
        and hide the state of the others.
        """
        root = self._copy(tmp_path)
        with open(os.path.join(root, "mod.py"), "a", encoding="utf-8",
                  newline="\n") as handle:
            handle.write("VALUE = 1\n")
        outcomes = list(mc.check(repo_root=root,
                                 mutations=(self._mutation(),)))
        assert [o.status for o in outcomes] == ["error"]
        assert "occurs 2 times" in outcomes[0].detail

    def test_a_surviving_mutation_is_reported_as_survived(self, tmp_path):
        """The middle verdict: the guard was removed and nothing noticed.

        The mutated module is not imported by the attributed selector, so its
        tests keep passing - the one result the whole harness exists to
        surface, and the only one that is easy to get wrong in the other
        direction (a harness that always says 'killed' passes every gate).
        """
        root = self._copy(tmp_path)
        with open(os.path.join(root, "other.py"), "w", encoding="utf-8",
                  newline="\n") as handle:
            handle.write("X = 1\n")
        blind = self._mutation(path="other.py", find="X = 1", replace="X = 2")
        outcomes = list(mc.check(repo_root=root, mutations=(blind,)))
        assert [o.status for o in outcomes] == ["survived"]
        assert "still passed with the guard removed" in outcomes[0].detail
        report = mc.as_json(outcomes)
        assert report["killed"] == 0 and report["ok"] is False

    def test_an_unrestorable_file_is_reported(self, tmp_path, monkeypatch):
        """If the anchor cannot be put back, the copy is no longer usable."""
        root = self._copy(tmp_path)
        monkeypatch.setattr(mc, "_restore", lambda *a: False)
        outcomes = list(mc.check(repo_root=root,
                                 mutations=(self._mutation(),)))
        assert [o.status for o in outcomes] == ["error"]
        assert "cannot restore" in outcomes[0].detail

    def test_a_timeout_during_the_mutation_is_reported(self, tmp_path,
                                                       monkeypatch):
        """A hung selector must fail the entry, not the whole harness.

        The control runs first and must succeed, so the stub answers the first
        call normally and then simulates the hang: a timeout in either phase
        would otherwise be indistinguishable from the other.
        """
        root = self._copy(tmp_path)
        real = mc.run_pytest
        calls = []

        def stub(root_, mutation, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                return real(root_, mutation, timeout)
            return None, "timed out after 1s"

        monkeypatch.setattr(mc, "run_pytest", stub)
        outcomes = list(mc.check(repo_root=root,
                                 mutations=(self._mutation(),)))
        assert [o.status for o in outcomes] == ["error"]
        assert outcomes[0].detail == "timed out after 1s"

    def test_keep_leaves_the_copy_behind(self, tmp_path):
        """`--keep` is the debugging affordance; it must not delete."""
        root = self._copy(tmp_path)
        made = []
        real_mkdtemp = mc.tempfile.mkdtemp

        def spy(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            made.append(path)
            return path

        mc.tempfile.mkdtemp = spy
        try:
            list(mc.check(repo_root=root, mutations=(self._mutation(),),
                          keep=True))
        finally:
            mc.tempfile.mkdtemp = real_mkdtemp
        assert made and os.path.isdir(made[0])
        shutil.rmtree(made[0], ignore_errors=True)

    def test_run_pytest_reports_a_timeout(self, tmp_path, monkeypatch):
        """The timeout branch of `run_pytest` itself (subprocess killed)."""
        def boom(*args, **kwargs):
            raise mc.subprocess.TimeoutExpired(cmd="pytest", timeout=1)

        monkeypatch.setattr(mc.subprocess, "run", boom)
        code, out = mc.run_pytest(str(tmp_path), self._mutation(), 1)
        assert code is None
        assert "timed out after 1s" in out

    def test_cli_list_prints_the_table(self, capsys):
        assert mc.main(["--list"]) == 0
        out = capsys.readouterr().out
        for mutation in mc.MUTATIONS:
            assert mutation.mid in out
        assert "test: pytest" in out

    def test_cli_rejects_an_unknown_id(self, capsys):
        assert mc.main(["--only", "no-such-mutation"]) == 1
        assert "unknown mutation id(s)" in capsys.readouterr().err


class TestRestore:
    """The copy is reused across entries, so restore must be exact."""

    def test_mutation_and_restore_round_trip(self, tmp_path):
        mutation = mc.MUTATIONS[0]
        src = tmp_path / "target.py"
        original = f"before\n{mutation.find}\nafter\n"
        src.write_text(original, encoding="utf-8")
        rel = os.path.basename(str(src))
        entry = mutation._replace(path=rel)
        mc.apply_mutation(str(tmp_path), entry)
        assert mutation.replace in src.read_text(encoding="utf-8")
        assert mc._restore(str(tmp_path), entry)
        assert src.read_text(encoding="utf-8") == original

    def test_an_ambiguous_anchor_is_refused(self, tmp_path):
        mutation = mc.MUTATIONS[0]
        src = tmp_path / "twice.py"
        src.write_text(f"{mutation.find}\n{mutation.find}\n",
                       encoding="utf-8")
        entry = mutation._replace(path=os.path.basename(str(src)))
        with pytest.raises(LookupError, match="occurs 2 times"):
            mc.apply_mutation(str(tmp_path), entry)


@pytest.mark.slow
class TestMutationsAreDetected:
    """The proof: remove each guard, require the attributed test to fail.

    Marked `slow` (a real source copy plus 1-2 pytest processes per entry).
    It does not need Node, media codecs, ffmpeg or an engine install: every
    attributed test is hermetic, which is the point of choosing these sites.
    """

    def test_every_mutation_is_killed(self):
        outcomes = list(mc.check())
        report = mc.as_json(outcomes)
        bad = [row for row in report["mutations"] if row["status"] != "killed"]
        assert not bad, mc.render(outcomes)

    def test_the_harness_reports_a_surviving_mutation(self):
        """The detector must be able to fail - proven, not assumed.

        A mutation with an unrelated selector removes the guard and asks a
        test that cannot see it, which is exactly what a real blind spot looks
        like.  Without this, a harness bug that always returns "killed" would
        pass the gate above.
        """
        blind = mc.MUTATIONS[0]._replace(
            selector=("tests/test_path_properties.py",))
        outcomes = list(mc.check(mutations=(blind,)))
        assert [o.status for o in outcomes] == ["survived"]
        assert mc.as_json(outcomes)["ok"] is False
