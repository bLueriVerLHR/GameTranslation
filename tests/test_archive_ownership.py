"""Processor ownership must fail before any archive backend or write occurs."""

from pathlib import Path

import pytest

from rpgmaker import archive, deliver, platform


@pytest.mark.parametrize("operation", ["create", "verify", "names", "extract"])
@pytest.mark.parametrize("foreign", ["/mnt/c/input.7z", "C:/input.7z", r"\\host\share\input.7z"])
def test_foreign_input_never_reaches_native_backend(monkeypatch, operation, foreign):
    monkeypatch.setattr(platform, "is_wsl", lambda: True)
    monkeypatch.setattr(archive, "_py7zr", lambda: pytest.fail("backend reached"))
    args = {
        "create": (foreign, "/tmp/output.7z"),
        "extract": (foreign, "/tmp/output"),
        "verify": (foreign,), "names": (foreign,),
    }
    with pytest.raises(platform.CrossSideError, match="cross-system"):
        getattr(archive, operation)(*args[operation])


@pytest.mark.parametrize("operation", ["create", "extract"])
def test_foreign_output_is_rejected_before_backend(monkeypatch, operation):
    monkeypatch.setattr(platform, "is_wsl", lambda: True)
    monkeypatch.setattr(archive, "_py7zr", lambda: pytest.fail("backend reached"))
    with pytest.raises(platform.CrossSideError):
        getattr(archive, operation)("/tmp/input", "/mnt/c/output")


@pytest.mark.parametrize("path", ["", " ", "bad\x00path"])
def test_invalid_io_path_is_not_cwd(path):
    with pytest.raises(ValueError):
        platform.require_native_paths("read", source=path)


def test_relative_path_and_link_target_are_classified(monkeypatch):
    monkeypatch.setattr(platform, "is_wsl", lambda: True)
    # Simulate resolution across a mount without creating real foreign files.
    monkeypatch.setattr(Path, "resolve", lambda self: Path("C:/linked/input"))
    with pytest.raises(platform.CrossSideError, match="source="):
        platform.require_native_paths("read", source="relative/input")


def test_native_paths_return_owned_resolved_references(tmp_path):
    owned = platform.require_native_paths("read", source=tmp_path / "missing")
    assert isinstance(owned["source"], platform.PathRef)
    assert Path(owned["source"]) == tmp_path / "missing"
    assert platform.ref(owned["source"]) is owned["source"]
    assert platform.side_of(owned["source"]) is owned["source"].side


def test_explicit_ownership_is_not_lost(monkeypatch):
    monkeypatch.setattr(platform, "is_wsl", lambda: True)
    owned = platform.PathRef.windows("relative/input")
    assert platform.ref(owned) is owned
    with pytest.raises(platform.CrossSideError):
        platform.require_native_paths("read", source=owned)


@pytest.mark.parametrize("path", [r"\\wsl$\Distro\tmp\input", r"\\wsl.localhost\Distro\tmp\input"])
def test_windows_processor_cannot_read_wsl_unc(monkeypatch, path):
    monkeypatch.setattr(platform, "is_wsl", lambda: False)
    monkeypatch.setattr(platform, "is_windows_os", lambda: True)
    with pytest.raises(platform.CrossSideError):
        platform.require_native_paths("read", source=path)


def test_native_roundtrip_with_path_refs(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "file.txt").write_text("synthetic", encoding="utf-8")
    packed = archive.create(platform.ref(source), platform.ref(tmp_path / "out.7z"), level=1)
    assert archive.verify(platform.ref(packed))
    assert "src/file.txt" in archive.names(platform.ref(packed))
    dest = platform.ref(tmp_path / "unpacked")
    assert archive.extract(platform.ref(packed), dest) is dest
    assert (Path(dest) / "src" / "file.txt").read_text(encoding="utf-8") == "synthetic"


def test_delivery_rejects_foreign_source_before_filesystem_work(monkeypatch):
    monkeypatch.setattr(platform, "is_wsl", lambda: True)
    monkeypatch.setattr(deliver.compress_mod, "compress", lambda *a, **k: pytest.fail("compression reached"))
    with pytest.raises(platform.CrossSideError):
        deliver.deliver("/mnt/c/source", games="/tmp/games", archives="/tmp/archives")


def test_delivery_rejects_foreign_local_archive_before_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(deliver.compress_mod, "compress", lambda *a, **k: pytest.fail("compression reached"))
    other = (platform.PathRef.posix("/tmp/output.7z") if platform.is_windows_os()
             else platform.PathRef.windows("C:/output.7z"))
    with pytest.raises(platform.CrossSideError):
        deliver.deliver(tmp_path, archive=other)
