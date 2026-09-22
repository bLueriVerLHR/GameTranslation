"""Every engine entry point must refuse the other storage side before I/O.

AGENTS.md makes the cross-system rule CRITICAL because violating it once
caused a machine-level incident.  `rpgmaker/archive.py` and `rpgmaker/deliver.py`
were the only gated entry points for a long time; the engine pipelines
(unpack, convert, clean, verify, audio, extraction) also read or write game
files with plain native Python I/O - typically ffmpeg, fontTools, UnityPy,
the XP3/DXArchive readers - and had nothing guarding them.

The gates all go through `platform.require_native_paths`, which compares each
path to the *processor*, not merely to the other paths in the same call.  The
first half of this file simulates a WSL processor (`platform.is_wsl -> True`)
and hands every entry point a Windows-side spelling; each must raise
`CrossSideError` before it touches the filesystem.  The second half checks the
same entry points are not broken for paths on the processor's own side.
"""
import pytest

from kirikiri import merge_font, pipeline, xp3pack, xp3tool
from kirikiri.kag import cli as kag_cli
from rpgmaker import platform
from tyrano import asar, audio, autoplay, build, clean, ui_lang, verify
from unity.rmunite import extract_game, prefill
from wolfrpg import dxarchive

ENTRY_POINTS = [
    "xp3pack.pack",
    "xp3tool.extract_all",
    "pipeline.unpack",
    "kag.convert",
    "merge_font.merge_fonts",
    "tyrano.build.unpack_game",
    "tyrano.asar.extract",
    "tyrano.clean.cleanup_all",
    "tyrano.audio.convert",
    "tyrano.verify.verify",
    "tyrano.ui_lang.cmd_dump",
    "tyrano.ui_lang.cmd_apply",
    "unity.extract_game.cmd",
    "unity.prefill.cmd",
    "wolfrpg.unpack_archive",
]


def _invoke(name, game, archive):
    """Call one gated entry point with `game`/`archive` as its inputs."""
    calls = {
        "xp3pack.pack": lambda: xp3pack.pack(game, archive),
        "xp3tool.extract_all": lambda: xp3tool.extract_all(archive,
                                                           game + "-out"),
        "pipeline.unpack": lambda: pipeline.unpack(
            {"_source": game, "_src": game + "-src", "_archives": "auto"}),
        "kag.convert": lambda: kag_cli.convert(unpacked=game,
                                               engine=game + "-engine",
                                               out_dir=game + "-out"),
        "merge_font.merge_fonts": lambda: merge_font.merge_fonts(
            game + "-cn.ttf", game + "-jp.ttf", game + "-merged.ttf", 2048),
        "tyrano.build.unpack_game": lambda: build.unpack_game(game,
                                                              game + "-work"),
        "tyrano.asar.extract": lambda: asar.extract(archive, game + "-out"),
        "tyrano.clean.cleanup_all": lambda: clean.cleanup_all(game),
        "tyrano.audio.convert": lambda: audio.convert(game),
        "tyrano.verify.verify": lambda: verify.verify(game),
        "tyrano.ui_lang.cmd_dump": lambda: ui_lang.cmd_dump(game),
        "tyrano.ui_lang.cmd_apply": lambda: ui_lang.cmd_apply(game),
        "unity.extract_game.cmd": lambda: extract_game.cmd(game, game + "-out"),
        "unity.prefill.cmd": lambda: prefill.cmd(game, "title"),
        "wolfrpg.unpack_archive": lambda: dxarchive.unpack_archive(
            archive, game + "-out", b"key"),
    }
    return calls[name]()


@pytest.fixture
def wsl(monkeypatch):
    """Simulate running on WSL, where a Windows-side path is foreign."""
    monkeypatch.setattr(platform, "is_wsl", lambda: True)


@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_foreign_path_is_refused_before_any_write(wsl, entry_point):
    with pytest.raises(platform.CrossSideError, match="cross-system"):
        _invoke(entry_point, "/mnt/c/game", "/mnt/c/game/data.xp3")


@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_refusal_names_the_offending_role(wsl, entry_point):
    """The error must say which argument was foreign, not just that one was."""
    with pytest.raises(platform.CrossSideError) as excinfo:
        _invoke(entry_point, "/mnt/c/game", "/mnt/c/game/data.xp3")
    message = str(excinfo.value)
    assert "/mnt/c/" in message
    assert "cannot handle" in message


def test_autoplay_gate_fires_when_the_file_exists(wsl, monkeypatch):
    """``patch_autoplay`` warns instead of gating for an absent file.

    That is deliberate - "the file is not here" is the more useful message.
    The gate still fires when the foreign file IS present, which is the case
    that would actually rewrite a Windows-side file.
    """
    monkeypatch.setattr("os.path.isfile", lambda path: True)
    with pytest.raises(platform.CrossSideError, match="cross-system"):
        autoplay.patch_autoplay("/mnt/c/game-work")


def test_verify_gates_the_source_argument_too(monkeypatch):
    """A same-side build plus a foreign original is still a cross-side read.

    Simulated by classifying the source spelling as Windows-side while the
    processor stays native, so only the source role can be the offender.
    """
    monkeypatch.setattr(platform, "is_windows_side",
                        lambda path: str(path).startswith("W:"))
    with pytest.raises(platform.CrossSideError, match="source="):
        verify.verify("build", source="W:/game")


def test_unity_extraction_gates_before_walking_the_tree(wsl, monkeypatch):
    """The gate must precede ``find_bundle_root``, which walks the game dir."""
    def _walked(*_args, **_kwargs):
        pytest.fail("the game directory was walked before the gate fired")

    monkeypatch.setattr(extract_game, "find_bundle_root", _walked)
    with pytest.raises(platform.CrossSideError):
        extract_game.cmd("/mnt/c/game", "/mnt/c/game-out")


def test_wolf_unpack_creates_no_output_directory(wsl, tmp_path):
    """The refusal must leave no half-created output tree behind."""
    out = tmp_path / "out"
    with pytest.raises(platform.CrossSideError):
        dxarchive.unpack_archive("/mnt/c/game/data.wolf", str(out), b"key")
    assert not out.exists()


def test_clean_dry_run_reports_instead_of_refusing(wsl, tmp_path):
    """``--dry-run`` only stats and prints, so it is deliberately ungated."""
    root = tmp_path / "build"
    root.mkdir()
    (root / "winmm.dll").write_bytes(b"hook")
    removed = clean.cleanup_all(str(root), dry_run=True)
    assert removed == [str(root / "winmm.dll")]
    assert (root / "winmm.dll").exists()


@pytest.mark.skipif(platform.is_wsl(),
                    reason="on WSL the native side is POSIX, which "
                           "resolve_ref() cannot express on a Windows host")
@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_native_paths_are_not_refused(entry_point, tmp_path):
    """The gates must not turn a same-side run into a refusal.

    The call may still fail for any other reason (missing input, unreadable
    archive, no ffmpeg); a `CrossSideError` is the regression this catches.
    """
    game = tmp_path / "game"
    game.mkdir()
    if entry_point == "tyrano.ui_lang.cmd_apply":
        # cmd_apply needs a mapping file; an empty table is a valid no-op run.
        mapping = tmp_path / "empty.json"
        mapping.write_text("{}", encoding="utf-8")
        try:
            ui_lang.cmd_apply(str(game), mapping=str(mapping))
        except BaseException as exc:  # noqa: BLE001 - a later failure is fine
            assert not isinstance(exc, platform.CrossSideError), (
                f"a native path was refused: {exc}")
        return
    try:
        _invoke(entry_point, str(game), str(game / "data.xp3"))
    except BaseException as exc:  # noqa: BLE001 - any later failure is fine
        # Any later, unrelated failure (missing input, unreadable archive,
        # absent ffmpeg/UnityPy, SystemExit from a CLI-style entry point) is
        # acceptable: this test only asserts the gate did not refuse a path
        # that is on the processor's own side.
        assert not isinstance(exc, platform.CrossSideError), (
            f"a native path was refused: {exc}")
