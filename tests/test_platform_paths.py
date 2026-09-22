#!/usr/bin/env python3
"""Platform detection, path domains
and the single-native-form conversions.

Split out of tests/test_config.py when rpgmaker/platform.py was split
(PLAN Phase 4): patching a name on the facade no longer reaches the code
that reads it, so each test now patches the module that owns the name.
"""


from rpgmaker import platform
import os

class TestPathConversions:
    def test_posix_windows_backslashes(self):
        assert platform.posix(r"C:\Games\Foo") == "C:/Games/Foo"

    def test_to_windows_path_wsl_form(self):
        assert platform.to_windows_path("/mnt/d/Games/Foo") == "D:\\Games\\Foo"

    def test_to_windows_path_windows_form_passthrough(self):
        assert platform.to_windows_path(r"C:\Games") == r"C:\Games"

    def test_to_windows_path_non_mnt_unchanged(self):
        assert platform.to_windows_path("/home/user/game") == "/home/user/game"

    def test_to_wsl_path(self):
        assert platform.to_wsl_path(r"C:\Games\Foo") == "/mnt/c/Games/Foo"

    def test_to_wsl_path_relative_unchanged(self):
        assert platform.to_wsl_path("Games") == "Games"

    def test_roundtrip(self):
        for p in ("/mnt/d/Games/Foo", r"D:\Games\Foo"):
            assert platform.to_windows_path(p) == r"D:\Games\Foo"
            assert platform.to_wsl_path(platform.to_windows_path(p)) == "/mnt/d/Games/Foo"

    def test_is_windows_side(self):
        # Only meaningful inside WSL; on native platforms it is always False.
        if platform.is_wsl():
            assert platform.is_windows_side("/mnt/c/foo")
            assert not platform.is_windows_side("/home/user/foo")
        else:
            assert platform.is_windows_side("/mnt/c/foo") is False


class TestLocalize:
    """localize() maps a stored native path to the current platform's view."""

    def test_wsl_windows_form_converted(self, monkeypatch):
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        assert platform.localize("D:/Games") == "/mnt/d/Games"
        assert platform.localize(r"C:\Games") == "/mnt/c/Games"

    def test_wsl_native_passthrough(self, monkeypatch):
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        assert platform.localize("/tmp/gametrans") == "/tmp/gametrans"
        assert platform.localize("3rd/7zz") == "3rd/7zz"

    def test_win32_mnt_form_converted(self, monkeypatch):
        monkeypatch.setattr(platform, "is_wsl", lambda: False)
        assert platform.localize("/mnt/d/Games") == "D:\\Games"

    def test_win32_native_passthrough(self, monkeypatch):
        monkeypatch.setattr(platform, "is_wsl", lambda: False)
        assert platform.localize("D:/Games") == "D:/Games"
        assert platform.localize("/home/user/game") == "/home/user/game"

    def test_empty_input(self, monkeypatch):
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        assert platform.localize("") == ""
        assert platform.localize(None) is None


class TestDisplayPath:
    """display_path() must never raise, whatever the CWD or the drives are.

    Bare ``os.path.relpath(path)`` resolves against ``os.getcwd()``, and on
    Windows the CWD can sit on another drive than the path (CI checks out to
    ``D:`` while ``tempfile`` hands out ``C:``), which raises
    ``ValueError: path is on mount 'C:', start on mount 'D:'``.  That failure
    reached the Windows CI runner through an asset WARN line.
    """

    def test_relative_to_the_given_root(self):
        root = os.path.join("C:", "data") if os.name == "nt" else "/data"
        path = os.path.join(root, "image", "a.png")
        assert platform.display_path(path, root) == os.path.join("image", "a.png")

    def test_without_a_root_the_path_is_untouched(self):
        """No root means no CWD lookup either; the helper stays location-free."""
        assert platform.display_path("C:/tmp/a.png") == "C:/tmp/a.png"
        assert platform.display_path("/tmp/a.png") == "/tmp/a.png"
        assert platform.display_path(os.path.join("sub", "a.png")) \
            == os.path.join("sub", "a.png")

    def test_other_drive_root_falls_back_instead_of_raising(self, monkeypatch):
        """The regression itself: a relpath that raises must degrade, not crash."""
        def boom(path, start=None):
            raise ValueError("path is on mount 'C:', start on mount 'D:'")

        monkeypatch.setattr(platform.os.path, "relpath", boom)
        assert platform.display_path("C:/tmp/a.png", "D:/build") == "C:/tmp/a.png"

    def test_a_path_outside_the_root_keeps_its_absolute_form(self):
        """A target with no relative spelling is not reported as ``../..``.

        Deliberately not skipped on POSIX: ``C:/tmp/a.png`` and ``D:/build``
        are both drive-less relative strings there, so ``relpath`` produces
        ``../../C:/tmp/a.png`` and the fallback to the given spelling is what
        keeps the log line readable.  On Windows the same call raises and the
        ``except ValueError`` branch answers instead; both paths end at the
        absolute form, which is the property worth pinning.
        """
        assert platform.display_path("C:/tmp/a.png", "D:/build") \
            == "C:/tmp/a.png"
