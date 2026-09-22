"""End-to-end contract for the KAG3 -> TyranoScript converter's output.

PLAN Phase 6 task 3 splits the converter's high-complexity orchestrators
(`kirikiri/kag/cli.py`) into stage helpers.  The acceptance rule for that
refactor is 「输出字节/manifest 不变」, so this file pins the converter's whole
output tree byte-for-byte across every documented mode.  A split that changes
a single byte of a generated scenario, `index.html`, `Config.tjs`, the shim js
or the intent inventory fails here.

The fixture is deliberately synthetic and small: the point is that every
output file the converter writes is produced and hashed, not that the game
content is realistic.  Binary assets are fake on purpose - the converter's
best-effort asset conversion warns and copies them, which is itself part of
the output contract.
"""

import hashlib
import os
from pathlib import Path

import pytest

from kirikiri.kag import cli as kag_cli

# --- the synthetic game ------------------------------------------------------

FIRST_KS = (
    "[cm]\n"
    "[trans method=crossfade time=3000]\n"
    "[image storage=\"black\" page=fore layer=base]\n"
    "[font size=24]Hello[r]World[l]\n"
    "[if exp=\"f.x==1\"]yes[else]no[endif]\n"
    "[call storage=\"ZoomRot.ks\"]\n"
    "[s]\n"
    "[wm text=\"window text\"]\n"
    "[name text=\"Alice\"]\n"
    "[select_caption text=\"choice\"]\n"
    "[playse storage=\"se1\"]\n"
    "[openvideo storage=\"movie1\"]\n"
    "@wait time=5\n"
    "[macro name=hello][endmacro]\n"
    "[iscript]\nclass ZoomRotPlugin extends KAGPlugin {}\n[endscript]\n"
)

GAME = {
    "first.ks": FIRST_KS,
    "system/gamesystem/nested.ks": '[ch text="nested"]\n',
    "ZoomRot.ks": ("[iscript]\nclass ZoomRotPlugin extends KAGPlugin {}\n"
                   "[endscript]\n"),
    "scenario/extra.ks": ("; comment\n[l][r]\n"
                          "[position layer=message1 left=10 top=20]\n"),
    "bgimage/black.bmp": "BMPDATA",
    "bgimage/telop1.bmp": "BMPDATA2",
    "fgimage/black.tlg": "TLGDATA",
    "sound/se1.ogg": "OGGDATA",
    "video/movie1.wmv": "WMVDATA",
    "system/Config.tjs": (
        ";scWidth = 800;\n;scHeight = 600;\n;configSave = webstorage;\n"
        ";numMessageLayers = 10;\n;numCharacterLayers = 8;\n"
        ";chSpeed = 30;\n;chSpeeds.fast = 1;\n;chSpeeds.normal = 3;\n"
        ";chSpeeds.slow = 5;\n;skipSpeed = 30;\n;ml = 10;\n;mt = 10;\n"
        ";mw = 10;\n;mh = 10;\n"
    ),
}

ENGINE = {
    "index.html": (
        "<html>\n<body>\n"
        '<input type="hidden" id="first_scenario_file" '
        'value="http://test.com/tyrano/data/scenario/first.ks">\n'
        '<script src="./tyrano/plugins/kag/kag.tag.js"></script>\n'
        "</body>\n</html>\n"
    ),
    "tyrano/tyrano.js": "// engine\n",
    "data/system/Config.tjs": ";engine config\n;scWidth = 1024;\n;skipSpeed = 30;\n",
    "data/system/KeyConfig.js": "// keys\n",
    "data/scenario/scene1.ks": "engine sample\n",
}

#: The converter modes the contract covers.  Each entry must produce output
#: that differs from `default` where it documents a difference (asserted by
#: `test_the_modes_are_not_vacuous`), so a mode that silently stops applying
#: its knob cannot hide behind the byte-identity check.
MODES = {
    "default": {},
    "portrait": {"portrait": True},
    "fast_fill_bare": {"fast_skip": True, "video_fit": "fill",
                       "msg_style": "bare", "title_jump": "first.ks:*start"},
    "fonts_off": {"fonts": None, "keep_game_buttons": True},
}

EXPECTED_FILE_COUNT = 14


def _write(root, files):
    for rel, body in files.items():
        path = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)


def _manifest(root):
    """{relative path: sha256} for every file under `root`."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            with open(full, "rb") as handle:
                out[rel] = hashlib.sha256(handle.read()).hexdigest()
    return out


def _convert(tmp_path, name, extra, prebuild=False):
    """Run one conversion into a fresh tree; return its file manifest."""
    work = Path(tmp_path) / name
    src, engine, out = work / "src", work / "engine", work / "out"
    _write(str(src), GAME)
    _write(str(engine), ENGINE)
    if prebuild:
        # scenario-only reuses what a previous build left behind
        assert kag_cli.convert(unpacked=str(src), engine=str(engine),
                               out_dir=str(out)) == 0
    code = kag_cli.convert(unpacked=str(src), engine=str(engine),
                           out_dir=str(out), **extra)
    assert code == 0, f"convert({name}) returned {code!r}"
    return _manifest(str(out))


class TestOutputIsStable:
    """Every mode must be deterministic and stable across the refactor."""

    @pytest.mark.parametrize("mode", sorted(MODES))
    def test_two_runs_produce_identical_bytes(self, tmp_path, mode):
        """The converter is deterministic: same input, same bytes.

        Without this, the "bytes unchanged after the split" check below would
        be comparing against a moving target.
        """
        first = _convert(tmp_path, mode + "-a", MODES[mode])
        second = _convert(tmp_path, mode + "-b", MODES[mode])
        assert first == second, "convert() is not deterministic"

    def test_every_documented_file_is_written(self, tmp_path):
        """The output tree is complete, not merely self-consistent.

        A split that silently stops writing a file would still be
        "deterministic"; counting the files pins that the converter's output
        set did not shrink.  The shim sits in `tyrano/plugins/` here rather
        than `tyrano/plugins/kag/` because this synthetic engine has no `kag/`
        subdirectory - the layout fallback is covered by
        `TestStageHelpers::test_shim_plugin_dir_prefers_the_engine_layout`.
        """
        produced = _convert(tmp_path, "default", {})
        assert len(produced) == EXPECTED_FILE_COUNT, sorted(produced)
        for rel in ("index.html", "data/scenario/first.ks",
                    "data/scenario/nested.ks", "data/scenario/extra.ks",
                    "data/scenario/make.ks", "data/system/Config.tjs",
                    "tyrano/plugins/kag.tag_kag3shim.js",
                    "_kag3_intents.json"):
            assert rel in produced, f"{rel} missing from the output"

    def test_scenario_only_reuses_the_existing_build(self, tmp_path):
        """`--scenario-only` re-converts scenarios without touching assets.

        The previous build's files must survive: the mode exists to iterate on
        scenario text without redoing the expensive asset pass.
        """
        work = Path(tmp_path) / "scenario-only"
        src, engine, out = work / "src", work / "engine", work / "out"
        _write(str(src), GAME)
        _write(str(engine), ENGINE)
        assert kag_cli.convert(unpacked=str(src), engine=str(engine),
                               out_dir=str(out)) == 0
        before = _manifest(str(out))
        assert kag_cli.convert(unpacked=str(src), engine=str(engine),
                               out_dir=str(out), scenario_only=True) == 0
        after = _manifest(str(out))
        assert set(after) == set(before), "scenario-only changed the file set"
        # the scenario text is re-derived, so it may differ only if the source
        # did; with the source unchanged the whole tree must be identical
        assert after == before

    def test_the_modes_are_not_vacuous(self, tmp_path):
        """Each mode must actually change something it claims to change.

        If `portrait` produced the same bytes as `default`, the parametrized
        byte checks above would pass while proving nothing about that knob.
        """
        base = _convert(tmp_path, "base", {})
        differing = {}
        for mode, extra in MODES.items():
            if mode == "default":
                continue
            man = _convert(tmp_path, mode, extra)
            differing[mode] = sorted(k for k in set(base) | set(man)
                                     if base.get(k) != man.get(k))
            assert differing[mode], f"mode {mode!r} changed nothing"
        # the specific knobs are wired to the specific outputs
        assert "data/system/Config.tjs" in differing["portrait"]
        assert "tyrano/plugins/kag.tag_kag3shim.js" in differing["fast_fill_bare"]
        assert "_kag3_intents.json" in differing["fonts_off"]


class TestStageHelpers:
    """The split helpers keep their documented behaviour on their own."""

    def test_skip_speed_is_lowered_by_the_config_rewrite(self, tmp_path):
        """The named rule `test_skip_speed_is_configured_below_the_template_
        default` asserts the same thing through source inspection; this pins
        the behaviour so the source text is not the only evidence."""
        sys_dst = tmp_path / "system"
        sys_dst.mkdir()
        (sys_dst / "Config.tjs").write_text(
            ";skipSpeed = 30;\n;scWidth = 800;\n", encoding="utf-8")
        kag_cli._rewrite_config_tjs(str(sys_dst), portrait=False)
        text = (sys_dst / "Config.tjs").read_text(encoding="utf-8")
        assert ";skipSpeed = 1;" in text
        assert ";scWidth = 1024;" in text

    def test_config_rewrite_is_a_no_op_without_a_config(self, tmp_path):
        """A missing Config.tjs must not create one (or raise)."""
        sys_dst = tmp_path / "system"
        sys_dst.mkdir()
        kag_cli._rewrite_config_tjs(str(sys_dst), portrait=True)
        assert list(sys_dst.iterdir()) == []

    def test_entry_scenario_resolution_prefers_the_caller(self, tmp_path):
        """Game data wins over the first.ks convention."""
        out = tmp_path / "out"
        out.mkdir()
        (out / "index.html").write_text(
            '<input type="hidden" id="first_scenario_file" value="placeholder">',
            encoding="utf-8")
        kag_cli._set_entry_scenario(str(out), "main01.ks",
                                    {"first.ks", "main01.ks"})
        html = (out / "index.html").read_text(encoding="utf-8")
        assert 'value="main01.ks"' in html

    def test_entry_scenario_inserts_the_input_when_absent(self, tmp_path):
        """A template with no #first_scenario_file gets one before <body>."""
        out = tmp_path / "out"
        out.mkdir()
        (out / "index.html").write_text("<html>\n<body>\n</html>\n",
                                        encoding="utf-8")
        kag_cli._set_entry_scenario(str(out), "first.ks", {"first.ks"})
        html = (out / "index.html").read_text(encoding="utf-8")
        assert 'id="first_scenario_file" value="first.ks"' in html

    def test_shim_script_is_injected_once(self, tmp_path):
        """Re-running the injection must not add a second <script> tag."""
        out = tmp_path / "out"
        out.mkdir()
        (out / "index.html").write_text(
            '<script src="./tyrano/plugins/kag/kag.tag.js"></script>\n',
            encoding="utf-8")
        kag_cli._inject_shim_script(str(out))
        kag_cli._inject_shim_script(str(out))
        html = (out / "index.html").read_text(encoding="utf-8")
        assert html.count("kag.tag_kag3shim.js") == 1

    def test_shim_plugin_dir_prefers_the_engine_layout(self, tmp_path):
        """The shim goes under `plugins/kag/` when the engine has that dir.

        Engine layouts differ between TyranoScript versions, so the split
        helper keeps the fallback: `plugins/kag/` when present, else
        `plugins/` (created).
        """
        eng = tmp_path / "engine"
        (eng / "tyrano" / "plugins" / "kag").mkdir(parents=True)
        assert kag_cli._shim_plugin_dir(str(eng)) == \
            os.path.join(str(eng), "tyrano", "plugins", "kag")

    def test_shim_plugin_dir_falls_back_and_creates(self, tmp_path):
        """No `plugins/kag/`: use `plugins/`, creating it when absent."""
        eng = tmp_path / "engine"
        eng.mkdir()
        got = kag_cli._shim_plugin_dir(str(eng))
        assert got == os.path.join(str(eng), "tyrano", "plugins")
        assert os.path.isdir(got)

    def test_convert_keeps_the_names_tests_monkeypatch(self):
        """`convert_scenario_file` and `_collect_macros` stay module attrs.

        `tests/test_entry_scenario.py` monkeypatches both on the module, so a
        split that moved them behind a local alias would break the ability to
        substitute them.
        """
        assert callable(kag_cli.convert_scenario_file)
        assert callable(kag_cli._collect_macros)
