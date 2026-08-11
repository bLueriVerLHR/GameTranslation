#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/verify.py build integrity checks."""
import json
import os

from conftest import make_game

from rpgmaker import verify


class TestPngSignatures:
    def test_good_pngs(self, game_dir, fake_tools):
        _root, web = game_dir
        assert verify.verify_pngs(web) == []

    def test_bad_png_detected(self, game_dir, fake_tools):
        _root, web = game_dir
        bad = os.path.join(web, "img", "pictures", "bad.png")
        with open(bad, "wb") as f:
            f.write(b"NOT A PNG")
        bads = verify.verify_pngs(web)
        assert bad in bads

    def test_workers_parameter(self, game_dir, fake_tools):
        _root, web = game_dir
        assert verify.verify_pngs(web, workers=1) == []


class TestDataJson:
    def test_all_parse(self, game_dir, fake_tools):
        _root, web = game_dir
        assert verify.verify_data_json(web) == []

    def test_corrupt_json_reported(self, game_dir, fake_tools):
        _root, web = game_dir
        p = os.path.join(web, "data", "Broken.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{not json")
        bad = verify.verify_data_json(web)
        assert any(fn == "Broken.json" for fn, _ in bad)

    def test_custom_encrypted_skipped(self, game_dir, fake_tools):
        _root, web = game_dir
        p = os.path.join(web, "data", "Encrypted.json")
        with open(p, "wb") as f:
            f.write(b"\xde\xad\xbe\xef")
        assert verify.verify_data_json(web) == []


class TestSystemFlags:
    def test_flags_ok(self, game_dir, fake_tools):
        _root, web = game_dir
        assert verify.verify_system_flags(web) == []

    def test_flags_set(self, game_dir, fake_tools):
        _root, web = game_dir
        p = os.path.join(web, "data", "System.json")
        with open(p, encoding="utf-8-sig") as f:
            s = json.load(f)
        s["hasEncryptedImages"] = True
        s["encryptionKey"] = "abcd" * 4
        with open(p, "w", encoding="utf-8") as f:
            json.dump(s, f)
        issues = verify.verify_system_flags(web)
        assert any("encryption flags" in i for i in issues)
        assert any("encryptionKey" in i for i in issues)

    def test_bom_detected(self, game_dir, fake_tools):
        _root, web = game_dir
        p = os.path.join(web, "data", "System.json")
        with open(p, encoding="utf-8-sig") as f:
            s = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write("\ufeff" + s)
        issues = verify.verify_system_flags(web)
        assert any("BOM" in i for i in issues)

    def test_missing_system_json(self, tmp_path, fake_tools):
        web = make_game(str(tmp_path / "g"))
        os.remove(os.path.join(web, "data", "System.json"))
        assert verify.verify_system_flags(web) == ["System.json missing"]


class TestAudioRefs:
    def test_refs_present(self, game_dir, fake_tools):
        _root, web = game_dir
        assert verify.verify_audio_refs(web) == []

    def test_missing_is_failure(self, game_dir, fake_tools):
        _root, web = game_dir
        p = os.path.join(web, "data", "System.json")
        with open(p, encoding="utf-8-sig") as f:
            s = json.load(f)
        s["titleBgm"]["name"] = "ghost"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(s, f)
        missing = verify.verify_audio_refs(web)
        assert ("bgm", "ghost") in missing

    def test_missing_in_source_too_is_warning(self, game_dir, tmp_path,
                                              fake_tools):
        root, web = game_dir
        src = make_game(str(tmp_path / "src"))
        p = os.path.join(web, "data", "System.json")
        with open(p, encoding="utf-8-sig") as f:
            s = json.load(f)
        s["titleBgm"]["name"] = "ghost"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(s, f)
        # source has no ghost either -> preexisting quirk, no failure
        assert verify.verify_audio_refs(web, source_dir=src) == []


class TestKeyFiles:
    def test_mz_keys(self, game_dir, fake_tools):
        _root, web = game_dir
        assert verify.verify_key_files(web) == []

    def test_mv_keys(self, tmp_path, fake_tools):
        web = make_game(str(tmp_path / "g"), mv=True)
        assert verify.verify_key_files(web) == []

    def test_missing_index(self, game_dir, fake_tools):
        _root, web = game_dir
        os.remove(os.path.join(web, "index.html"))
        missing = verify.verify_key_files(web)
        assert "index.html" in missing


class TestVerifyAll:
    def test_clean_build_passes(self, game_dir, fake_tools):
        _root, web = game_dir
        assert verify.verify_all(web) == []

    def test_corruption_fails(self, game_dir, fake_tools):
        _root, web = game_dir
        with open(os.path.join(web, "img", "pictures", "pic1.png"), "wb") as f:
            f.write(b"broken")
        issues = verify.verify_all(web)
        assert issues  # PNG group reported

    def test_decode_mode_with_fake_tools(self, game_dir, fake_tools):
        _root, web = game_dir
        assert verify.verify_all(web, decode=True, workers=1) == []
