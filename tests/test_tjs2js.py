"""Unit tests for kirikiri/tjs2js.py (TJS2 -> JS converter)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kirikiri import tjs2js


class TestDictLiterals:
    def test_simple(self):
        assert tjs2js.convert_expr("setOptions(%[gvolume:20])") == "setOptions({gvolume: 20})"

    def test_quoted_key(self):
        out = tjs2js.convert_expr("%['a b':1]")
        assert '1' in out and 'a b' in out


class TestSprintf:
    def test_sprintf(self):
        out = tjs2js.convert_expr('"%02d".sprintf(i)')
        assert out == '"%02d".sprintf(i)'


class TestConcat:
    def test_tjs_concat(self):
        assert tjs2js.convert_concat('a & b') == 'a + b'

    def test_logical_and_preserved(self):
        assert tjs2js.convert_concat('a && b') == 'a && b'
        assert tjs2js.convert_concat('a &= b') == 'a &= b'


class TestCount:
    def test_member_count(self):
        assert tjs2js.convert_count('f.t_voice.count') == 'f.t_voice.length'

    def test_in_expr(self):
        assert tjs2js.convert_expr('intrandom(1,t_vo.count)') == 'intrandom(1,t_vo.length)'

    def test_identifier_not_touched(self):
        assert tjs2js.convert_count('counter = 1') == 'counter = 1'
        assert tjs2js.convert_count('countpage=true') == 'countpage=true'


class TestClasses:
    def test_class_to_prototype(self):
        src = """class Foo {
var a;
function Foo() { a = 1; }
function bar(x) { return a + x; }
}"""
        out = tjs2js.convert_classes(src)
        assert "function Foo()" in out
        assert "this.a" in out
        assert "Foo.prototype.bar" in out
        assert "this.a" in out

    def test_property_accessors(self):
        src = """class Foo {
var v;
property P { getter { return v; } setter(x) { v = x; } }
}"""
        out = tjs2js.convert_classes(src)
        assert "Object.defineProperty(Foo.prototype, 'P'" in out
        assert "get: function" in out
        assert "set: function" in out

    def test_getter_does_not_swallow_the_setter_block(self):
        # A greedy `getter {...}(.*)}` match captured the following
        # `setter(x){...}` block into the getter body, so raw TJS
        # `setter(ma){` was emitted into the JavaScript.  That is invalid JS
        # and stopped the script on the file that contained it (a game boot
        # died right after loading the file with this pattern).
        src = """class Foo {
var v;
property P {
  getter {
    return v;
  }
  setter(x) {
    v = x;
  }
}
}"""
        out = tjs2js.convert_classes(src)
        assert "setter(" not in out, out
        assert "getter" not in out, out
        assert out.count("get: function") == 1
        assert out.count("set: function") == 1
        # the getter body must not contain the setter's assignment
        get_body = out.split("get: function", 1)[1].split("set: function", 1)[0]
        assert "x" not in get_body.split("//")[0].replace("this.v", "")
        # field references are rewritten to `this.<name>`
        assert "return this.v" in get_body

    def test_property_with_getter_only(self):
        src = """class Foo {
var v;
property P { getter { return v; } }
}"""
        out = tjs2js.convert_classes(src)
        assert "get: function" in out
        assert "set: function" not in out

    def test_property_with_setter_only(self):
        src = """class Foo {
var v;
property P { setter(x) { v = x; } }
}"""
        out = tjs2js.convert_classes(src)
        assert "set: function" in out
        assert "setter(" not in out

    def test_getter_body_keeps_nested_braces(self):
        # Brace pairing (not a greedy/lazy regex) so an `if` inside a getter
        # does not truncate the body.
        src = """class Foo {
var v;
property P {
  getter {
    if (v) { return 1; }
    return 0;
  }
  setter(x) { v = x; }
}
}"""
        out = tjs2js.convert_classes(src)
        assert "return 0" in out
        assert "setter(" not in out


class TestCasts:
    def test_int_cast(self):
        assert tjs2js.convert_expr("tf.t_lpos=((int)sf.lay_ch_left)") == "tf.t_lpos=(Math.floor(sf.lay_ch_left))"

    def test_int_cast_nested(self):
        assert "Math.floor" in tjs2js.convert_expr("(int)(f.a+1)")

    def test_backslash_div(self):
        assert tjs2js.convert_expr("f.tm\\f.ani_frame") == "Math.floor(f.tm / f.ani_frame)"

    def test_amp_ref(self):
        assert tjs2js.convert_expr("&FukuSabunChk(a,b)") == "FukuSabunChk(a,b)"
        assert tjs2js.convert_expr("a && b") == "a && b"

    def test_incontextof(self):
        out = tjs2js.convert_expr("{click:function{tf.wait=1;} incontextof this},1")
        assert "incontextof" not in out


class TestIscript:
    def test_full_conversion(self):
        out = tjs2js.convert_iscript("class Foo {\nvar a;\nfunction Foo(){a=0;}\n}\nvar x = arr.count;\n")
        assert "this.a" in out
        assert "arr.length" in out
