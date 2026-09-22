#!/usr/bin/env python3
"""Layer contract for the test suite (PLAN Phase 5 tasks 2, 3 and 9).

Three jobs, all of them about *what a test needs* rather than what it asserts:

1. **Marker taxonomy.**  `pyproject.toml` registers the layers (`slow`,
   `media`, `node`, `engine_runtime`, `wsl`, `browser`, `device`) and sets
   `strict_markers = true`, so the fast layer is exactly the unmarked tests.

2. **Skip budget.**  A skip means "the capability was not there".  The suite
   had 25 such sites with four genuinely different causes, and a bare
   ``pytest.skip("...")`` cannot distinguish "optional dev tool" from "the
   fixture is missing because it is gitignored" - the second is a coverage
   hole hiding behind a green run.  Every site must name the missing
   capability, and the total count must not grow silently.

3. **Layer contract.**  Each layer is a documented command with a stated cost
   and external dependency, and every layer excluded from PRs is run by the
   nightly job.  Marking a test without running it anywhere is the same as
   deleting it.

The dependency rule is grounded in *observable* evidence rather than import
guessing: a skip site is proof that the test needs something, so the gate maps
the skip reason to the layer that supplies it.  A test that imports PIL to
build a fixture stays fast; one that only works when a real codec or a Node
binary exists must say so.

The checks are static (AST + config), so they cost nothing and cannot flake.
"""
import ast
import os
import re
import subprocess

try:
    import tomllib                 # Python 3.11+
except ImportError:               # pragma: no cover - exercised on 3.10 ci
    import tomli as tomllib        # dev extra; see pyproject.toml

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The registry lives in pyproject.toml; this tuple mirrors it so a rename in
# one place cannot go unnoticed.
EXPECTED_MARKERS = (
    "slow",
    "media",
    "node",
    "engine_runtime",
    "wsl",
    "browser",
    "device",
)

# Layers that name acceptance steps run outside pytest (a real device, a real
# browser, a real WSL box).  They are registered so a future test can use them,
# and are deliberately exempt from "some test must carry it".
RUNNER_LAYERS = frozenset({"wsl", "browser", "device"})

# The documented fast (PR) layer: everything that needs nothing local.
FAST_LAYER_EXPR = " and ".join(f"not {m}" for m in EXPECTED_MARKERS)

# Layers the nightly job must run.
NIGHTLY_MARKERS = ("slow", "media", "node", "engine_runtime")

# Skip reason -> the layer it proves.  Matched case-insensitively against the
# reason text, so the reason is load-bearing: rewording it away from a known
# capability is what makes the gate ask why.
SKIP_REASON_LAYERS = {
    "node": ("node.js", "node binary"),
    "media": ("libvpx", "pyav", "encoder"),
    "slow": ("numba",),
    "engine_runtime": ("engine source",),
}

# Skips that are NOT layer boundaries: the condition is the host platform, a
# missing dev-only tool, or a defensive guard against an incomplete checkout.
# No marker can make such a test run, so each is enumerated here with its
# rationale rather than hidden behind a line-number allowlist (which rots).
GUARD_SKIP_REASONS = (
    ("git is unavailable",
     "git is a dev-only tool; the check is meaningless without it"),
    ("git unavailable",
     "same as above"),
    ("case-insensitive filesystem",
     "the host filesystem cannot represent the case difference needed"),
    ("cannot read",
     "defensive guard against an unreadable file mid-scan"),
    ("ruff is not installed",
     "optional dev tool (pyproject [dev] extra), not a test layer"),
    ("uv is not installed",
     "optional dev tool (uv manages the lockfile), not a test layer"),
    ("setuptools is unavailable",
     "build backend is missing, so no wheel can be produced at all"),
    ("no tlg fixtures present",
     "tests/fixtures/tlg/ is tracked, so absence means an incomplete "
     "checkout rather than a missing capability"),
    ("no real tlg files present",
     "same fixture set as above"),
)

# `pytest.importorskip("X")` proves only that X is an optional package.  Which
# optional packages the suite may need is a packaging question, not a layer
# question: they come from pyproject extras and a clean CI install has them
# all.  Recorded explicitly so a new optional import is a deliberate act.
OPTIONAL_IMPORTS = frozenset({
    "PIL",      # [images] extra
    "av",       # core dependency; the import check is a build-capability guard
    "asar",     # core dependency, same
    "numba",    # [images] extra, JIT acceleration for the TLG fast path
})

# Video ENCODING is never optional in a way that is not a layer boundary: the
# encoder needs a PyAV build carrying libvpx-vp9.  Probing is deliberately NOT
# listed - reading a container, or failing on a missing file, needs no codec
# and is covered by the fast layer.
MEDIA_ONLY_CALLS = ("media.transcode_to_webm",)

SKIP_CALLS = frozenset({"skip", "importorskip", "xfail"})

# Markers pytest defines itself; they are not layers and must not be reported
# as unregistered.
BUILTIN_MARKS = frozenset({
    "parametrize", "skip", "skipif", "xfail", "usefixtures",
    "filterwarnings", "tryfirst", "trylast", "timeout", "no_cover",
    "dependency",
})

# Measured when this gate was written.  Growing it is a deliberate act (a new
# dependency or a new fixture) that must be recorded here, so a skip cannot
# appear quietly inside an unrelated change.  `tools/skip_report.py` prints the
# same inventory with each site's capability, and CI runs it so the number is
# never the only thing anyone sees.
#
# 25 -> 27: `tests/test_kag_shim_runtime.py` (Phase 5 task 7) puts the shim's
# pure functions under a real Node.js binary, so it carries the same "Node.js
# is required" guard as the audio runtime test, twice (helpers and test body).
# 27 -> 28: `tests/test_lint.py` gained the burn-down budget gate (Phase 6
# task 1), which needs ruff just like the two lint gates already there.
SKIP_BUDGET = 28

# This gate cannot scan itself (its own string literals look like skip sites).
SCAN_EXEMPT = frozenset({"tests/test_test_layers.py"})

MARKER_USE_RE = re.compile(r"pytest\.mark\.([A-Za-z_][A-Za-z0-9_]*)")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _git_ls_files(pattern):
    """Tracked + untracked (but not ignored) files matching `pattern`.

    ``--others --exclude-standard`` matters: a new test file must be visible
    to this gate before it is committed, otherwise it can be the one file that
    breaks the contract on someone else's machine.
    """
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         pattern],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise AssertionError(f"git ls-files failed: {out.stderr.strip()}")
    return [line for line in out.stdout.splitlines() if line]


def _test_files():
    files = _git_ls_files("tests/*.py")
    assert len(files) > 50, (
        "the test scan found only %d file(s) - the pathspec is wrong"
        % len(files))
    return [f for f in files if f not in SCAN_EXEMPT]


def _parse(rel):
    with open(os.path.join(REPO_ROOT, rel), "rb") as handle:
        return handle.read().decode("utf-8")


def _marker_names(node):
    """Marker names inside an expression, e.g. ``pytest.mark.media``.

    ``@pytest.mark.media`` (call-less) and ``@pytest.mark.media(...)`` are both
    handled by passing ``dec.func`` for the latter.
    """
    found = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Attribute):
            continue
        inner = sub.value
        if isinstance(inner, ast.Attribute) \
                and isinstance(inner.value, ast.Name) \
                and inner.value.id == "pytest" and inner.attr == "mark":
            found.add(sub.attr)
    return found


def _pytestmark_of(body):
    """Markers from a ``pytestmark = ...`` assignment in a module/class body.

    ``pytestmark`` is legal inside a class body, not only at module level, and
    that is how the whole-class markers in this suite are written.
    """
    found = set()
    for node in body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "pytestmark":
                found |= _marker_names(node.value)
    return found


def _scope_markers(tree):
    """Map every AST scope (class/function) to the markers applying to it.

    Markers are inherited downwards: a module ``pytestmark`` reaches every
    scope, and a class ``pytestmark`` reaches its methods.  The walk is
    recursive so nesting is respected - a flat ``ast.walk`` cannot tell a
    method's own markers from its class's.
    """
    scopes = []

    def visit(node, inherited):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef,
                                  ast.AsyncFunctionDef)):
                found = set(inherited) | _pytestmark_of(child.body)
                for dec in child.decorator_list:
                    found |= _marker_names(dec.func
                                           if isinstance(dec, ast.Call)
                                           else dec)
                scopes.append((child, found))
                visit(child, found)
            else:
                visit(child, inherited)

    visit(tree, _pytestmark_of(tree.body))
    return scopes


def _marker_scope_for(tree):
    """Return ``lookup(lineno)``: the markers of the innermost scope
    containing that line, module-level markers included.

    Two attributes ride on the returned function: ``file_markers()`` for the
    union over the whole file, and ``in_helper(lineno)`` - True when the
    tightest scope is a fixture/helper rather than a test, in which case only
    the file-level union is a fair requirement.
    """
    module_markers = _pytestmark_of(tree.body)
    scopes = _scope_markers(tree)

    def innermost(lineno):
        best = None
        best_span = None
        for node, _markers in scopes:
            start = node.lineno
            end = getattr(node, "end_lineno", start) or start
            if start <= lineno <= end:
                span = end - start
                if best_span is None or span < best_span:
                    best, best_span = node, span
        return best

    def lookup(lineno):
        node = innermost(lineno)
        if node is None:
            return set(module_markers)
        for scope, markers in scopes:
            if scope is node:
                return set(markers)
        return set(module_markers)

    def file_markers():
        found = set(module_markers)
        for _scope, markers in scopes:
            found |= markers
        return found

    def in_helper(lineno):
        node = innermost(lineno)
        if node is None:
            return False
        if isinstance(node, ast.ClassDef):
            return not node.name.startswith("Test")
        return not node.name.startswith("test")

    lookup.in_helper = in_helper
    lookup.file_markers = file_markers
    return lookup


def _declared_markers(tree):
    found = set()
    for _node, markers in _scope_markers(tree):
        found |= markers
    return found

def _skip_sites(tree):
    """(lineno, call-name, reason-source, arg-source) for every skip-ish
    call.

    For ``importorskip`` the ``arg-source`` is the package name (that IS the
    capability); for ``skip``/``xfail`` it is the reason, and ``reason-source``
    only becomes non-empty when ``reason=`` was passed as a keyword.
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(
            fn, "id", None)
        if name not in SKIP_CALLS:
            continue
        arg = ast.unparse(node.args[0]) if node.args else ""
        reason = arg if name != "importorskip" else ""
        for kw in node.keywords:
            if kw.arg == "reason":
                reason = ast.unparse(kw.value)
        out.append((node.lineno, name, reason, arg))
    return sorted(out)


def _reason_text(source):
    """The reason a skip names, lowercased: the literal when it is a constant,
    otherwise the source expression.

    The fallback matters because a formatted guard reason
    (``"cannot read %s: %s" % (rel, exc)``) is not a literal, and the guard it
    names is still visible in the source.
    """
    try:
        value = ast.literal_eval(source)
    except Exception:  # noqa: BLE001 - a formatted reason is not a literal
        return source.lower()
    return value.lower() if isinstance(value, str) else source.lower()


def _dotted_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _pyproject():
    with open(os.path.join(REPO_ROOT, "pyproject.toml"), "rb") as handle:
        return tomllib.load(handle)


def _workflow():
    with open(os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml"),
              encoding="utf-8") as handle:
        return handle.read()


# ---------------------------------------------------------------------------
# marker taxonomy
# ---------------------------------------------------------------------------

def test_registry_and_gate_agree_on_the_marker_set():
    """pyproject.toml is the single source; this list mirrors it."""
    ini = _pyproject()["tool"]["pytest"]["ini_options"]
    declared = {entry.split(":", 1)[0].strip() for entry in ini["markers"]}
    assert declared == set(EXPECTED_MARKERS), (
        f"pyproject.toml markers {sorted(declared)} != expected {sorted(EXPECTED_MARKERS)}")
    assert ini.get("strict_markers") is True, (
        "strict_markers must be true, otherwise a typo'd marker is silently "
        "accepted and the test runs in the wrong layer")


def test_every_declared_marker_says_what_it_needs():
    """A marker is a contract: it must state the dependency, not just a name."""
    ini = _pyproject()["tool"]["pytest"]["ini_options"]
    for entry in ini["markers"]:
        name, _, description = entry.partition(":")
        assert description.strip(), f"marker {name.strip()!r} has no description"


def test_no_unregistered_layer_marker_is_used():
    """With strict_markers a typo fails at collection; this reports it as a
    named test instead of a mysterious collection error.  pytest's own marks
    (parametrize, skipif, ...) are not layers and are ignored."""
    malformed = sorted(
        (rel, marker)
        for rel in _test_files()
        for marker in MARKER_USE_RE.findall(_parse(rel))
        if marker not in EXPECTED_MARKERS and marker not in BUILTIN_MARKS)
    assert not malformed, (
        f"these files use unregistered markers: {malformed[:10]}")


def test_runner_layers_are_the_only_unused_markers():
    used = set()
    for rel in _test_files():
        used |= set(MARKER_USE_RE.findall(_parse(rel)))
    unused = set(EXPECTED_MARKERS) - used - RUNNER_LAYERS
    assert not unused, (
        f"no test carries these markers, so the layer is empty: {sorted(unused)}")


def test_skips_prove_their_layer_and_declare_it():
    """A skip site is proof the test needs an optional capability; the layer
    that supplies it must be marked on the enclosing scope.

    The gate does not care what a test imports, only what it says it needs.
    Two kinds of skip are exempt because no marker can make them run: a host
    platform condition and a dev-tool that is not a test layer
    (GUARD_SKIP_REASONS).  A skip inside a helper declares the helper's own
    dependency, so the marker belongs on the helper even though pytest itself
    would ignore it there.
    """
    issues = []
    for rel in _test_files():
        tree = ast.parse(_parse(rel))
        lookup = _marker_scope_for(tree)
        for lineno, name, reason, arg in _skip_sites(tree):
            if name == "importorskip":
                # `pytest.importorskip("X")` names a package, not a layer: an
                # optional import is a packaging concern, and the CI install
                # brings every extra.
                pkg = arg.strip('"\'')
                if pkg not in OPTIONAL_IMPORTS:
                    issues.append(
                        "%s:%d importorskip(%s): an optional import must be "
                        "listed in OPTIONAL_IMPORTS with a rationale"
                        % (rel, lineno, pkg or arg))
                continue
            text = _reason_text(reason)
            capabilities = [text]
            if any(pattern in cap
                   for pattern, _why in GUARD_SKIP_REASONS
                   for cap in capabilities):
                continue
            needed = set()
            for marker, needles in SKIP_REASON_LAYERS.items():
                if any(needle in cap for needle in needles
                       for cap in capabilities):
                    needed.add(marker)
            if not needed:
                issues.append(
                    "%s:%d skips on %r, which names no known layer; either "
                    "add the capability to SKIP_REASON_LAYERS or list it in "
                    "PLATFORM_SKIP_REASONS" % (rel, lineno, reason))
                continue
            have = lookup(lineno)
            if lookup.in_helper(lineno):
                # pytest cannot select a fixture or helper on its own, so the
                # honest requirement is that some test in this file carries
                # the layer.  The marker still belongs on the helper: that is
                # where the dependency is documented.
                have = lookup.file_markers()
            missing = needed - have
            if missing:
                issues.append(
                    "%s:%d skips without declaring layer %s (has %s)"
                    % (rel, lineno, sorted(missing), sorted(have) or "none"))
    assert not issues, "\n".join(issues)


def test_video_calls_declare_the_media_layer():
    """Encoding/decoding video needs a PyAV build with libvpx-vp9; that is a
    layer boundary, and no import-level exemption applies."""
    issues = []
    for rel in _test_files():
        tree = ast.parse(_parse(rel))
        lookup = _marker_scope_for(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            dotted = _dotted_name(node.func)
            if not dotted:
                continue
            if any(dotted == c or dotted.endswith("." + c)
                   for c in MEDIA_ONLY_CALLS) and "media" not in lookup(node.lineno):
                issues.append("%s:%d calls %s without @pytest.mark.media"
                              % (rel, node.lineno, dotted))
    assert not issues, "\n".join(issues)


# ---------------------------------------------------------------------------
# skip budget
# ---------------------------------------------------------------------------

def test_skip_sites_stay_within_budget():
    """Skips are coverage holes; the count is pinned so one cannot appear
    inside an unrelated change without a deliberate edit here."""
    total = 0
    by_file = {}
    for rel in _test_files():
        count = len(_skip_sites(ast.parse(_parse(rel))))
        if count:
            by_file[rel] = count
            total += count
    assert total == SKIP_BUDGET, (
        "skip budget changed: %d sites, budget %d\n%s"
        % (total, SKIP_BUDGET,
           "\n".join("  %s: %d" % kv for kv in sorted(by_file.items()))))


def test_every_skip_names_the_missing_capability():
    """A bare ``pytest.skip()`` tells the reader nothing, and makes the CI
    skip report useless."""
    problems = []
    for rel in _test_files():
        for lineno, name, reason, _arg in _skip_sites(ast.parse(_parse(rel))):
            if name == "importorskip":
                continue                    # the argument IS the capability
            if not reason or reason in ("''", '""'):
                problems.append("%s:%d calls %s with no reason"
                                % (rel, lineno, name))
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------
# layer contract
# ---------------------------------------------------------------------------

def test_the_fast_layer_excludes_every_marker():
    """The documented fast-layer expression is the negation of the whole
    registry, so adding a marker cannot leave tests in the PR layer by
    accident."""
    for marker in EXPECTED_MARKERS:
        assert f"not {marker}" in FAST_LAYER_EXPR
    assert "addopts" in _pyproject()["tool"]["pytest"]["ini_options"]
    workflow = _workflow()
    assert FAST_LAYER_EXPR in workflow, (
        "the CI fast job must select the PR layer explicitly, with exactly "
        f"the expression the gate builds from the marker registry ({FAST_LAYER_EXPR!r}); "
        "otherwise a marked test still runs on every PR and the marker "
        "means nothing")


def test_the_workflow_is_valid_yaml_and_declares_its_jobs():
    """A syntax error in ci.yml is invisible locally and only surfaces as a
    workflow that never starts.  Parsing it here turns that into a failing
    test.  (The unquoted `:` inside a step *name* is a real example that got
    through an edit and was caught only by loading the file.)"""
    try:
        import yaml
    except ImportError:         # pragma: no cover - dev extra is installed
        pytest.skip("PyYAML is not installed (pyproject [dev] extra)")
    document = yaml.safe_load(_workflow())
    assert isinstance(document, dict), "ci.yml is not a mapping"
    jobs = document.get("jobs")
    assert isinstance(jobs, dict) and jobs, "ci.yml declares no jobs"
    assert {"test", "coverage", "lock", "wheel", "audit", "nightly"} \
        <= set(jobs), f"ci.yml lost a job: {sorted(jobs)}"
    # YAML 1.1 parses the bare key `on` as the boolean True, so accept both.
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict), "ci.yml declares no triggers"
    assert "schedule" in triggers, (
        "the nightly layers need a schedule trigger, or they never run")
    for name, job in jobs.items():
        assert isinstance(job.get("steps"), list) and job["steps"], (
            f"job {name!r} has no steps")
        assert job.get("runs-on"), f"job {name!r} has no runner"


def test_every_excluded_layer_runs_somewhere():
    """Every layer excluded from PRs must be run by the nightly job, or
    marking a test is the same as deleting it."""
    workflow = _workflow()
    assert "nightly" in workflow.lower(), (
        "no nightly/soak job runs the excluded layers")
    for marker in NIGHTLY_MARKERS:
        assert (f'-m "{marker}"') in workflow, (
            f"the nightly job does not run the {marker} layer")


def test_the_nightly_job_replays_the_fast_layer_in_random_order():
    """A one-off random-order run rots; this repository's recorded lesson is
    that a check verified by hand has to become a gate.

    `pytest-randomly` is deliberately not in the [dev] extra (it activates
    through an entry point and would shuffle every local and PR run), so the
    nightly job installs it and replays the *fast layer* - the slow/media/node
    layers get their own runs and do not need a second shuffle.
    """
    workflow = _workflow()
    assert "pytest-randomly" in workflow, (
        "the nightly job does not install pytest-randomly, so random order is "
        "verified by hand at best")
    assert "-p randomly" in workflow, (
        "pytest-randomly is installed but never selected")
    shuffled = workflow.split("-p randomly", 1)[1][:400]
    assert FAST_LAYER_EXPR in shuffled, (
        "the random-order run must replay the fast layer with the same "
        "expression the PR job uses, otherwise it covers a different set of "
        "tests than the gate it is meant to validate")


def _workflow_steps():
    """(job, step-name, run-text) for every shell step in ci.yml.

    Guards below read the parsed document rather than the raw text, so a check
    cannot be satisfied by a comment or a job name that merely mentions the
    right word.
    """
    import yaml

    document = yaml.safe_load(_workflow())
    steps = []
    for job, body in (document.get("jobs") or {}).items():
        steps.extend(
            (job, step.get("name", ""), step["run"])
            for step in body.get("steps") or [] if "run" in step)
    assert len(steps) > 10, f"the workflow scan found {len(steps)} steps"
    return steps


def test_no_ci_step_uses_a_backslash_line_continuation():
    """A `run:` block is a plain shell script on every runner.

    Windows runners execute it with PowerShell, where a trailing backslash is
    a literal argument and the next line starts a NEW command - the PR test
    step ran `python -m pytest tests ... \\` and then `-m "not slow and ..."`
    as a separate command, so the whole Windows matrix was invalid.  YAML
    folding (one long line, or a `>` block) is portable; a backslash is not.
    """
    offenders = [
        f"{job} / {name or '<unnamed>'}: {line.strip()}"
        for job, name, text in _workflow_steps()
        for line in str(text).splitlines()
        if line.rstrip().endswith("\\")
    ]
    assert not offenders, (
        "these CI steps use a POSIX line continuation that PowerShell does "
        "not honour:\n" + "\n".join(offenders))


def test_ci_enforces_the_recorded_coverage_floors():
    """Producing a coverage artifact is not enforcing anything.

    The floors live in tests/coverage_floor.json and are only compared when
    `tools/check_coverage.py` runs; the coverage job used to upload XML and
    stop there, so two regressions sat in a green pipeline.
    """
    coverage_steps = [text for job, _name, text in _workflow_steps()
                      if job == "coverage"]
    assert coverage_steps, "ci.yml has no coverage job"
    joined = "\n".join(coverage_steps)
    assert "tools/check_coverage.py" in joined, (
        "the coverage job never runs the floor checker")
    assert "coverage.json" in joined, (
        "the floor checker needs a JSON report (`--cov-report=json:...`)")
    assert "--cov-branch" in joined, (
        "the recorded floors are branch floors; measuring statement coverage "
        "in CI compares two different numbers")


def test_ci_wheel_job_installs_what_its_step_runs():
    """The wheel job's pytest step must be able to run pytest.

    It installed only `build`, so `python -m pytest tests/test_wheel_contents
    .py` failed with "unrecognized arguments" and the packaging gate never
    actually ran in CI.
    """
    wheel_steps = [text for job, _name, text in _workflow_steps()
                   if job == "wheel"]
    assert wheel_steps, "ci.yml has no wheel job"
    joined = "\n".join(wheel_steps)
    assert "pytest" in joined, "the wheel job never installs pytest"
    assert "dist/*.whl" in joined, (
        "the wheel job must install the wheel it just built, with its "
        "declared dependencies - that is the shape an operator gets")


def test_ci_prints_the_skip_inventory():
    """A skip budget alone reports a number, not a reason.

    `tests/test_test_layers.py` fails when the count moves or a reason names no
    layer, but a green run still hides the shape of the hole.  Task 9 requires
    CI to report WHAT is missing, so the reporting step has to be in the
    workflow - a tool nobody runs answers nothing.
    """
    workflow = _workflow()
    assert "tools/skip_report.py" in workflow, (
        "CI does not report the skip inventory; add the step to the test job")
    assert "--verbose" in workflow.split("tools/skip_report.py", 1)[1][:200], (
        "the skip report must list each site, not only the totals")
