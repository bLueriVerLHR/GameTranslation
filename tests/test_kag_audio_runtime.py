"""Behavioral tests of the generated audio channel, without media or a browser.

Marked `node`: the shim logic is executed by a real Node.js binary, so this
belongs to the nightly layer (`-m node`) rather than the PR fast layer.
"""

import subprocess

import pytest

from kirikiri.convert_kag import RUNTIME_SHIM_IIFE
from rpgmaker.tool_registry import find_node


pytestmark = pytest.mark.node


def test_audio_channel_ignores_obsolete_callbacks():
    node = find_node()
    if not node:
        pytest.skip("Node.js is required for the audio runtime test")
    start = RUNTIME_SHIM_IIFE.index("var _se_make = function")
    end = RUNTIME_SHIM_IIFE.index("var _searr =", start)
    source = RUNTIME_SHIM_IIFE[start:end]
    harness = r"""
const assert = require('node:assert/strict');
const __kag3_assets = () => ({});
const __kag3_stem = s => s;
const __kag3_log = () => {};
let throws = false;
class Audio {
  constructor(url) { this.url = url; this.events = {}; }
  addEventListener(name, fn) { this.events[name] = fn; }
  pause() {}
  play() {
    if (throws) throw new Error('play failed');
    return {catch: fn => { this.reject = fn; }};
  }
}
""" + source + r"""
const channel = _se_make();
channel.play({storage:'first.ogg'});
const old = channel._el;
channel.play({storage:'second.ogg'});
assert.equal(channel.status, 'play');
old.reject();
old.events.error();
old.events.ended();
assert.equal(channel.status, 'play');
channel._el.events.ended();
assert.equal(channel.status, 'stop');
channel.play({storage:'third.ogg'});
channel._el.reject();
assert.equal(channel.status, 'stop');
channel.play({storage:'fourth.ogg'});
channel._el.events.error();
assert.equal(channel.status, 'stop');
channel.setOptions({loop:1, gvolume:25}).play({storage:'loop.ogg'});
channel._el.events.ended();
assert.equal(channel.status, 'play');
assert.equal(channel._el.volume, 0.25);
channel.stop();
assert.equal(channel.status, 'stop');
throws = true;
channel.play({storage:'failed.ogg'});
assert.equal(channel.status, 'stop');
"""
    result = subprocess.run([node, "-e", harness], capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            timeout=15)
    assert result.returncode == 0, result.stderr
