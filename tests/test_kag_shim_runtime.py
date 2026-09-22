#!/usr/bin/env python3
"""Runtime tests of the generated KAG3 shim functions, executed by Node.

Marked `node`: a real Node.js binary runs the extracted shim code, so this is
the nightly layer (`-m node`), not the PR fast layer.

Why this file exists (PLAN Phase 5 task 7): the shim suite used to assert that
a *fragment of source text* appears inside a JS string (`assert "replace(...)"
in MAP_ENGINE_JS`).  That pins spelling, not behaviour - the assertion passes
if the function is defined and then never called, if a caller passes the wrong
argument, or if two functions disagree about the path form.  Any one of those
ships a silent no-op, which is why `docs/kirikiri-tyrano.md` keeps repeating
that a no-op must never be reported as success.

Measured regressions the behavioural tests below replace fragment checks for:

* `[mapaction storage="title.ma"]` was rewritten to `../fgimage/TITLE.MA`, the
  shim's own fetch prefixed `./data/`, and the browser requested
  `/fgimage/TITLE.MA` -> 404.  Found in the server request log, not on screen.
* the title menu's region image was never found (`hasRegionCanvas: false`)
  because its key was built as `fgimage/title_p` instead of `title_p`, so the
  artwork drew but no click could be hit-tested.

The pure functions are extracted from the shim source by name (brace matching,
not index slicing) and concatenated into one Node program with an assertion
harness.  DOM-dependent functions are out of scope here; they belong to the
browser layer.

Every assertion below was verified to FAIL when its rule is removed from the
shim (`.tmp` probe, six mutations): 5 were caught immediately, and 2 needed a
stronger input first - a transparent pixel whose red byte is non-zero (so
reading red instead of alpha changes the answer) and a comment line carrying a
colon.  One mutation is deliberately NOT covered: dropping
`if (line.charAt(0) === ';') continue;` from `parse_ma` is **equivalent** -
measured over 8 comment shapes (`; 1: x=1`, `; 0x1: q=4`, `;-1: z=3`, ...),
`parseInt` on the text before the first colon is always NaN, so the existing
`isNaN` guard already skips it.  There is nothing to test; the check is
readability, not behaviour.
"""
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from kirikiri.kag import shims  # noqa: E402
from rpgmaker.tool_registry import find_node  # noqa: E402


pytestmark = pytest.mark.node


def _extract(source, name):
    """Return the whole ``var <name> = ...;`` statement from `source`.

    Slicing between two literal strings (the previous approach) breaks as soon
    as a function body contains the delimiter, and silently returns the wrong
    span when a function is reordered.  Counting braces from the declaration's
    opening brace is exact as long as the body has no unbalanced brace inside
    a string or comment - which is why a leftover mismatch asserts instead of
    returning a partial function.
    """
    marker = f"var {name} = function"
    start = source.find(marker)
    assert start >= 0, f"{name} is gone from the shim source"
    open_at = source.index("{", start)
    depth = 0
    for pos in range(open_at, len(source)):
        char = source[pos]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = source.index(";", pos)
                return source[start:end + 1]
    raise AssertionError(f"unbalanced braces while extracting {name}")


def _run(harness, functions):
    """Run `harness` in Node with `functions` prepended.  Returns stdout."""
    node = find_node()
    if not node:
        pytest.skip("Node.js is required for the shim runtime tests")
    body = "\n".join(_extract(shims.MAP_ENGINE_JS, name) for name in functions)
    program = "const assert = require('node:assert/strict');\n" + body + "\n" + harness
    return subprocess.run([node, "-e", program], capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            timeout=20)


def _assert_ok(result, label):
    assert result.returncode == 0, f"{label} failed:\n{result.stderr}"


# ------------------------------------------------------------ path handling

def test_data_url_strips_the_dot_dot_prefix():
    """The 404 regression: a resolved `../dir/file` must not escape data/."""
    result = _run(r"""
assert.equal(__kag3_data_url('../fgimage/title.ma'), './data/fgimage/title.ma');
assert.equal(__kag3_data_url('fgimage/title.ma'), './data/fgimage/title.ma');
assert.equal(__kag3_data_url('title.ma'), './data/title.ma');
// null/undefined must not produce the string "null"
assert.equal(__kag3_data_url(null), './data/');
assert.equal(__kag3_data_url(undefined), './data/');
// only a LEADING ../ is stripped; inner segments are meaningful
assert.equal(__kag3_data_url('a/../b.png'), './data/a/../b.png');
""", ("__kag3_data_url",))
    _assert_ok(result, "data_url")


def test_stem_is_the_single_path_to_key_derivation():
    """Every key derived from a path must agree, or a lookup silently misses."""
    result = _run(r"""
// the measured failure: a canonical path used as a map key
assert.equal(__kag3_stem('fgimage/title_p'), 'title_p');
assert.equal(__kag3_stem('../fgimage/TITLE.MA'), 'title');
assert.equal(__kag3_stem('title_p'), 'title_p');
assert.equal(__kag3_stem('a/b/c/Ev01.png'), 'ev01');
assert.equal(__kag3_stem(''), '');
assert.equal(__kag3_stem(null), '');
// a dot in a directory name must not be treated as an extension
assert.equal(__kag3_stem('a.b/c'), 'c');
""", ("__kag3_stem",))
    _assert_ok(result, "stem")


def test_resolve_accepts_every_form_a_tag_can_carry():
    """`pm.storage` may be a bare name, a canonical path or a resolved path."""
    result = _run(r"""
const map = {'title': {n: 'title'}, 'fgimage/ev01': {n: 'ev01'}};
assert.deepEqual(__kag3_resolve('title', map), {n: 'title'});
assert.deepEqual(__kag3_resolve('../fgimage/TITLE.MA', map), {n: 'title'});
assert.deepEqual(__kag3_resolve('fgimage/ev01.png', map), {n: 'ev01'});
assert.equal(__kag3_resolve('missing', map), null);
assert.equal(__kag3_resolve('', map), null);
assert.equal(__kag3_resolve(null, map), null);
assert.equal(__kag3_resolve('title', {}), null);
// the extension-less fallback must not crash on a key that is all extension
assert.equal(__kag3_resolve('.png', {}), null);
""", ("__kag3_stem", "__kag3_resolve"))
    _assert_ok(result, "resolve")


# ------------------------------------------------------------- map parsing

def test_parse_ma_reads_the_kag3_map_action_format():
    result = _run(r"""
const a = __kag3_parse_ma('1: storage=title.ma\n2: target=*start\n');
assert.deepEqual(a[1], ' storage=title.ma');
assert.deepEqual(a[2], ' target=*start');
// comments, blank lines and malformed lines are skipped, not fatal.
// The comment carries a colon on purpose: a `;` line with a colon looks
// like a valid entry to everything except the comment check, so a test
// whose comment has no colon passes even with that check removed.
const b = __kag3_parse_ma('; note: 1: storage=wrong.ma\n\nnope\n3:onenter=foo()\n');
assert.deepEqual(Object.keys(b), ['3']);
assert.deepEqual(b[3], 'onenter=foo()');
// CRLF input (a Windows-authored .ma file) must parse identically
assert.deepEqual(__kag3_parse_ma('1: a\r\n2: b\r\n'),
                 __kag3_parse_ma('1: a\n2: b\n'));
// a region index of 0 is valid KAG3 (the whole-map region)
assert.deepEqual(__kag3_parse_ma('0: storage=x.ks')[0], ' storage=x.ks');
assert.deepEqual(__kag3_parse_ma(''), {});
""", ("__kag3_parse_ma",))
    _assert_ok(result, "parse_ma")


def test_region_hit_test_reads_the_alpha_channel_red_index():
    """Region index 0 means "no region" and must never be reported as a hit."""
    result = _run(r"""
function fakeMap(pixels) {
  return {
    regionCanvas: {width: 4, height: 1},
    regionCtx: {getImageData: function (x, y, w, h) {
      return {data: [pixels[x][0], 0, 0, pixels[x][1]]};
    }},
  };
}
// index 1 is TRANSPARENT but carries a non-zero red byte: only the alpha
// channel decides, so a red-only read would report region 5 here.  (First
// version used red 0 for the transparent pixel, so dropping the alpha test
// changed nothing and the mutation survived.)
const map = fakeMap([[7, 255], [5, 0], [3, 255], [9, 255]]);
assert.equal(__kag3_region_of(map, 0, 0), 7);    // opaque -> its index
assert.equal(__kag3_region_of(map, 1, 0), 0);    // transparent -> 0
assert.equal(__kag3_region_of(map, 2, 0), 3);
// out of bounds in either axis is "no region", never a crash
assert.equal(__kag3_region_of(map, 4, 0), 0);
assert.equal(__kag3_region_of(map, -1, 0), 0);
assert.equal(__kag3_region_of(map, 0, 1), 0);
assert.equal(__kag3_region_of(map, 0, -1), 0);
// a map whose canvas never loaded has no hit test at all
assert.equal(__kag3_region_of({}, 0, 0), 0);
assert.equal(__kag3_region_of(null, 0, 0), 0);
""", ("__kag3_region_of",))
    _assert_ok(result, "region_of")


# ------------------------------------------------------------ video lookup

def test_video_resolver_keys_by_basename_without_extension():
    node = find_node()
    if not node:
        pytest.skip("Node.js is required for the shim runtime tests")
    body = _extract(shims.VIDEO_SHIM_JS, "__kag3_vid_resolve")
    program = (
        "const assert = require('node:assert/strict');\n"
        "var window = {__kag3_videos: {'op': 'data/video/op.webm'}};\n"
        "var __kag3_vid_map = function () { return window.__kag3_videos; };\n"
        + body + "\n"
        "assert.equal(__kag3_vid_resolve('op'), 'data/video/op.webm');\n"
        "assert.equal(__kag3_vid_resolve('video/OP.webm'), 'data/video/op.webm');\n"
        "// an unknown name falls through to the name itself (the tag will 404\n"
        "// visibly rather than silently resolving to a wrong movie)\n"
        "assert.equal(__kag3_vid_resolve('nope'), 'nope');\n"
        "assert.equal(__kag3_vid_resolve(''), null);\n"
        "assert.equal(__kag3_vid_resolve(null), null);\n"
    )
    result = subprocess.run([node, "-e", program], capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            timeout=20)
    _assert_ok(result, "vid_resolve")


# ---------------------------------------------------------------- the source

def test_the_shim_source_still_has_the_functions_under_test():
    """Guard against the extraction silently finding nothing.

    `_extract` asserts on a missing name, but a test that is never reached
    because the module attribute was renamed would fail with an obscure
    AttributeError instead of naming the contract.
    """
    for name in ("__kag3_data_url", "__kag3_stem", "__kag3_resolve",
                 "__kag3_parse_ma", "__kag3_region_of"):
        _extract(shims.MAP_ENGINE_JS, name)
    _extract(shims.VIDEO_SHIM_JS, "__kag3_vid_resolve")
