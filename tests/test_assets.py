#!/usr/bin/env python3
"""Registered font resolution.

Split out of tests/test_config.py when rpgmaker/assets.py was split
(PLAN Phase 4): patching a name on the facade no longer reaches the code
that reads it, so each test now patches the module that owns the name.
"""



from rpgmaker import assets

class TestFonts:
    def test_cjk_font_env_override(self, monkeypatch, tmp_path):
        f = tmp_path / "cjk.otf"
        f.write_bytes(b"x")
        monkeypatch.setenv("CJK_FONT_PATH", str(f))
        assert assets.find_cjk_font() == str(f)

    def test_jp_font_env_override(self, monkeypatch, tmp_path):
        f = tmp_path / "jp.otf"
        f.write_bytes(b"x")
        monkeypatch.setenv("JP_FONT_PATH", str(f))
        assert assets.find_jp_font() == str(f)

    def test_missing_fonts_return_none(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CJK_FONT_PATH", raising=False)
        monkeypatch.delenv("JP_FONT_PATH", raising=False)
        monkeypatch.setattr(assets, "FONTS_DIR", tmp_path / "no-fonts")
        monkeypatch.setattr(assets, "read_font_paths", list)
        assert assets.find_cjk_font() is None
        assert assets.find_jp_font() is None

    def test_font_paths_file_is_read_through_the_private_mapping(
            self, monkeypatch, tmp_path):
        """A relative entry resolves against the file's own directory, so the
        local font-paths file stays machine-independent."""
        font = tmp_path / "fonts" / "SomeCJK-Regular.otf"
        font.parent.mkdir()
        font.write_bytes(b"x")
        paths_file = tmp_path / "local_font_path.txt"
        paths_file.write_text("# comment\nfonts/SomeCJK-Regular.otf\n"
                              "fonts/missing.otf\n", encoding="utf-8")
        monkeypatch.setattr(assets, "private_path",
                            lambda key: paths_file if key == "font-paths"
                            else tmp_path)
        assert assets.read_font_paths() == [str(font)]
