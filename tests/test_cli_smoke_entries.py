#!/usr/bin/env python3
"""Every live CLI entry must actually start - from the checkout, on a
non-UTF-8 console.

Why this file exists
--------------------
`rpgmaker/inventory.py` knows which modules are live and what command runs
them, but nothing checked that those commands *work*.  A sweep of all 64
inventoried entries with `--help` found the same defect in ten of them:

    UnicodeEncodeError: 'charmap' codec can't encode characters in
    position 232-233: character maps to <undefined>

The tools' docstrings contain CJK (game tags such as `[iscript]`, Japanese
examples, `【名前】`), and `--help` is answered by the CLI framework *before*
any command body runs.  The UTF-8 console repair lives in `logsetup.setup()`,
which the command body calls - so the documented `python -m <tool> --help`
died on a cp1252 console while the command itself worked.  `cliutil.run()`
now repairs the streams itself; these tests keep it that way.

The probe deliberately forces `PYTHONIOENCODING=cp1252` so the Windows
console condition is reproduced on Linux CI too.  Without that, Ubuntu's
UTF-8 default would hide the whole class of defect.
"""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

import rpgmaker.inventory as inventory

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: `--help` must work for every probed entry.  This set is empty now: the
#: last two hand-rolled argv parsers (`tools.build_csv_template`,
#: `tools.patch_names`) were moved onto `cliutil.command_app` in Phase 3, so
#: there are no longer any entries that cannot answer `--help`.  Keep the
#: constant so a reintroduced hand-rolled parser has an obvious place to be
#: recorded (and fails `test_no_entry_is_pinned_as_legacy` below).
LEGACY_ARGV_ENTRIES = set()

#: Prints a report rather than help; `--json` is its machine surface and a
#: missing optional tool legitimately yields exit 1.
JSON_ENTRIES = {"rpgmaker.doctor"}

#: Exit codes are not interesting for these; only "the process started and
#: produced its documented output".
EXIT_CODES = {"rpgmaker.doctor": (0, 1)}

PROBE_TIMEOUT = 120


def _module_argvs():
    """Map inventoried module -> argv list, from the inventory's own entries.

    Reading the entry strings (rather than guessing `python -m <module>`)
    means a wrong entry string in the inventory fails here instead of being
    papered over.
    """
    found = {}
    for record in inventory.MODULES:
        entry = record.entry
        if not entry or entry == "package":
            continue
        marker = "python -m "
        if marker not in entry:
            continue
        for token in entry.split("/"):
            token = token.strip()
            if token.startswith(marker):
                module = token[len(marker):].strip().split()[0]
                found[record.module] = [sys.executable, "-m", module]
    assert found, "no CLI entries found in rpgmaker/inventory.py"
    return found


def _probe(argv):
    """Run one command with a cp1252 console, returning the CompletedProcess."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"   # the Windows console condition
    env["GT_NO_PROBE"] = "1"             # keep tool discovery off the disk
    env.pop("PYTHONPATH", None)
    return subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=PROBE_TIMEOUT, env=env)


@pytest.fixture(scope="module")
def help_probes():
    """Every `--help` probe result, run in parallel once for the module."""
    argvs = _module_argvs()
    targets = {
        module: argv + ["--help"] for module, argv in argvs.items()
        if module not in LEGACY_ARGV_ENTRIES and module not in JSON_ENTRIES}
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(
            lambda item: (item[0], _probe(item[1])), targets.items()))


def _module_id(module):
    return module


PROBED = sorted(set(_module_argvs()) - LEGACY_ARGV_ENTRIES - JSON_ENTRIES)


class TestEveryEntryAnswersHelp:
    @pytest.mark.parametrize("module", PROBED, ids=_module_id)
    def test_help_exits_zero(self, module, help_probes):
        proc = help_probes[module]
        assert proc.returncode == 0, (
            "%s --help failed with %d\n--- stdout ---\n%s\n--- stderr ---\n%s"
            % (module, proc.returncode, proc.stdout[-2000:],
               proc.stderr[-2000:]))

    @pytest.mark.parametrize("module", PROBED, ids=_module_id)
    def test_help_prints_usage(self, module, help_probes):
        """A zero exit with no usage text means the entry did nothing."""
        out = help_probes[module].stdout
        assert "Usage" in out or "usage" in out, (
            f"{module} --help printed no usage line:\n{out[:2000]}")

    def test_the_cjk_help_regression_is_covered(self, help_probes):
        """At least one probed entry must carry CJK in its help text.

        The defect this file exists for only shows up when the help contains
        characters a cp1252 console cannot encode.  If a refactor strips the
        Japanese examples out of every docstring, the parametrised cases
        above would keep passing while testing nothing - so assert the
        condition is still present.
        """
        def non_ascii(text):
            return any(ord(ch) > 127 for ch in text)

        offenders = [m for m, p in help_probes.items() if non_ascii(p.stdout)]
        assert offenders, (
            "no probed entry printed non-ASCII help text; the cp1252 "
            "regression check is no longer exercising anything")


class TestEntriesThatAreNotHelp:
    def test_no_entry_is_pinned_as_legacy(self):
        """Every runnable entry must answer `--help` (Phase 3 end state).

        While `LEGACY_ARGV_ENTRIES` was non-empty this file deliberately
        pinned the hand-rolled parsers' no-argument behaviour instead of
        testing help.  All of them now use `cliutil.command_app`, so the
        exemption set must stay empty - a new member means someone added a
        tool that cannot explain itself.
        """
        assert not LEGACY_ARGV_ENTRIES, (
            "these entries cannot answer --help; normalise them onto "
            f"cliutil.command_app: {sorted(LEGACY_ARGV_ENTRIES)}")

    @pytest.mark.parametrize("module", sorted(JSON_ENTRIES), ids=_module_id)
    def test_json_report_is_valid_and_typed(self, module):
        """`--json` is the machine surface: it must parse and be complete."""
        proc = _probe([sys.executable, "-m", module, "--json"])
        assert proc.returncode in EXIT_CODES[module], (
            "%s --json returned %d\n%s" % (module, proc.returncode,
                                           proc.stderr[-2000:]))
        payload = json.loads(proc.stdout)
        assert set(payload) >= {"ok", "checks", "tools"}
        assert isinstance(payload["ok"], bool)
        assert payload["checks"], "doctor reported no checks at all"
        for check in payload["checks"]:
            assert set(check) >= {"label", "ok", "detail"}, check


class TestTheInventoryIsFullyCovered:
    def test_every_probed_module_is_a_live_entry(self):
        """Only `active` entries are probed — a retired tool is not a gate.

        `maintenance` is a legitimate permanent status (post-incident data
        repair that cannot be automated), and a maintenance tool being
        runnable is exactly the point; what must never happen is a
        `superseded`/`dead` entry being smoke-tested as if it were live.
        """
        for module in _module_argvs():
            status = inventory.status_of(module)
            assert status is not None, module
            assert status in ("active", "maintenance"), (
                f"{module} is probed but its status is {status!r}; retire it or drop it "
                "from the probe")

    def test_executable_entries_are_not_silently_skipped(self):
        """Every runnable `active`/`maintenance` entry must be probed.

        `package` entries and library modules have no command, so they are
        exempt; anything else must land in one of the three groups.  This is
        what stops a new tool being added to the inventory with no smoke
        coverage.
        """
        argvs = _module_argvs()
        unprobed = []
        for record in inventory.MODULES:
            if record.status not in ("active", "maintenance"):
                continue
            if record.module not in argvs:
                continue
            if record.kind in ("shared-lib", "core"):
                # Library modules with a convenience `__main__` but no
                # documented command surface of their own.
                continue
            if record.module in JSON_ENTRIES:
                continue
            if record.module not in PROBED:
                unprobed.append(record.module)
        assert not unprobed, unprobed
