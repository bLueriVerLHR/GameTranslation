#!/usr/bin/env python3
"""Registered font resolution.

Split out of tests/test_config.py when rpgmaker/assets.py was split:
patching a name on the facade no longer reaches the code that reads it, so
each test now patches the module that owns the name.
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


class TestDiscoverFont:
    """The auto-discovery scan of the registered font directory.

    The directory is replaced by a temporary one, so the result does not
    depend on which fonts the machine happens to have registered.
    """

    @staticmethod
    def _font(directory, name):
        path = directory / name
        path.write_bytes(b"x")
        return path

    def test_regular_weight_wins_over_the_first_match(self, monkeypatch,
                                                     tmp_path):
        monkeypatch.setattr(assets, "FONTS_DIR", tmp_path)
        self._font(tmp_path, "GlowSansSC-Bold.otf")
        regular = self._font(tmp_path, "GlowSansSC-Regular.otf")
        assert assets.discover_font("glowsanssc") == str(regular)

    def test_first_match_is_used_without_a_regular_variant(self, monkeypatch,
                                                           tmp_path):
        monkeypatch.setattr(assets, "FONTS_DIR", tmp_path)
        only = self._font(tmp_path, "GlowSansJ-Bold.otf")
        assert assets.discover_font("glowsansj") == str(only)

    def test_the_filename_match_is_case_insensitive(self, monkeypatch,
                                                   tmp_path):
        """The pattern is lower-case by contract; the file name is folded."""
        monkeypatch.setattr(assets, "FONTS_DIR", tmp_path)
        upper = self._font(tmp_path, "GLOWSANSSC-Light.otf")
        assert assets.discover_font("glowsanssc") == str(upper)

    def test_directories_and_other_names_are_skipped(self, monkeypatch,
                                                     tmp_path):
        monkeypatch.setattr(assets, "FONTS_DIR", tmp_path)
        (tmp_path / "GlowSansSC-Regular.otf").mkdir()
        self._font(tmp_path, "Other.otf")
        assert assets.discover_font("glowsanssc") is None

    def test_absent_directory_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(assets, "FONTS_DIR", tmp_path / "no-fonts")
        assert assets.discover_font("glowsanssc") is None

    def test_find_cjk_font_falls_back_to_the_directory(self, monkeypatch,
                                                      tmp_path):
        monkeypatch.setattr(assets, "FONTS_DIR", tmp_path)
        monkeypatch.setattr(assets, "read_font_paths", list)
        monkeypatch.delenv("CJK_FONT_PATH", raising=False)
        regular = self._font(tmp_path, "GlowSansSC-Regular.otf")
        assert assets.find_cjk_font() == str(regular)

    def test_an_unlistable_directory_returns_none(self, monkeypatch):
        """A directory that raises on listing is a recoverable condition."""
        class _Unlistable:
            @staticmethod
            def is_dir():
                return True

            @staticmethod
            def iterdir():
                raise OSError("listing denied")

        monkeypatch.setattr(assets, "FONTS_DIR", _Unlistable)
        assert assets.discover_font("glowsanssc") is None


class TestFontPathFallbacks:
    """The ordered fallbacks behind the two environment variables."""

    @staticmethod
    def _font(directory, name):
        path = directory / name
        path.write_bytes(b"x")
        return path

    def test_an_unreadable_font_paths_file_is_empty(self, monkeypatch,
                                                   tmp_path):
        monkeypatch.setattr(assets, "private_path",
                            lambda key: tmp_path / "absent.txt")
        assert assets.read_font_paths() == []

    def test_cjk_font_uses_the_first_recorded_path(self, monkeypatch,
                                                  tmp_path):
        font = self._font(tmp_path, "cjk.otf")
        monkeypatch.delenv("CJK_FONT_PATH", raising=False)
        monkeypatch.setattr(assets, "read_font_paths", lambda: [str(font)])
        assert assets.find_cjk_font() == str(font)

    def test_jp_font_uses_the_second_recorded_path(self, monkeypatch,
                                                  tmp_path):
        cjk = self._font(tmp_path, "cjk.otf")
        jp = self._font(tmp_path, "jp.otf")
        monkeypatch.delenv("JP_FONT_PATH", raising=False)
        monkeypatch.setattr(assets, "read_font_paths",
                            lambda: [str(cjk), str(jp)])
        assert assets.find_jp_font() == str(jp)

    def test_jp_font_falls_back_to_the_directory(self, monkeypatch, tmp_path):
        monkeypatch.setattr(assets, "FONTS_DIR", tmp_path)
        monkeypatch.setattr(assets, "read_font_paths", list)
        monkeypatch.delenv("JP_FONT_PATH", raising=False)
        jp = self._font(tmp_path, "GlowSansJ-Regular.otf")
        assert assets.find_jp_font() == str(jp)
