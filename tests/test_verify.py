#!/usr/bin/env python3
"""Unit tests for rpgmaker/verify.py build integrity checks."""
import glob
import json
import os
import random


from conftest import make_game

from rpgmaker import verify, tool_registry


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

    def test_jpeg_content_png_tolerated(self, game_dir, fake_tools):
        """JPEG bytes under a .png name are a known engine practice
        (content sniffing makes them loadable): reported as WARN, not
        a verification failure."""
        _root, web = game_dir
        p = os.path.join(web, "img", "pictures", "jpegish.png")
        with open(p, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        assert verify.verify_pngs(web) == []

    def test_jpeg_content_does_not_fail_verify_all(self, game_dir,
                                                   fake_tools):
        _root, web = game_dir
        with open(os.path.join(web, "img", "pictures", "j.png"), "wb") as f:
            f.write(b"\xff\xd8\xff\xe1" + b"\x00" * 20)
        assert verify.verify_all(web) == []

    def test_truncated_jpeg_magic_still_bad(self, game_dir, fake_tools):
        """A file too short to carry the full JPEG magic is corruption,
        not a foreign-format image."""
        _root, web = game_dir
        p = os.path.join(web, "img", "pictures", "trunc.png")
        with open(p, "wb") as f:
            f.write(b"\xff\xd8")
        assert p in verify.verify_pngs(web)


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

    def test_decode_mode_flags_undecodable_files(self, game_dir, fake_tools):
        """The synthetic game's .ogg files are byte stubs, so an in-process
        PyAV decode check must report them - previously the fake ffmpeg was
        trusted and the decode pass looked clean."""
        _root, web = game_dir
        issues = verify.verify_all(web, decode=True, workers=1)
        assert issues
        flat = " | ".join(str(x) for group in issues
                          for x in (group if isinstance(group, list) else [group]))
        assert "decode" in flat.lower()

    def test_decode_mode_clean_on_a_real_ogg(self, game_dir, fake_tools):
        from conftest import real_ogg
        _root, web = game_dir
        for rel in ("audio/bgm/bgm1.ogg", "audio/se/se1.ogg",
                    "audio/bgm/bgm_mono.ogg"):
            real_ogg(os.path.join(web, rel))
        assert verify.verify_all(web, decode=True, workers=1) == []

    def test_decode_works_without_ffmpeg(self, game_dir, monkeypatch):
        """Decoding is in-process (PyAV): no ffmpeg binary is needed."""
        _root, web = game_dir
        monkeypatch.setattr(tool_registry, "find_ffmpeg", lambda: None)
        verify.verify_all(web, decode=True, workers=1)   # must not raise


class TestRandomSamplePng:
    """Random-sampled PNG batches must verify cleanly, and random corruption
    must be found (AGENTS.md task-rule 4: sample randomly instead of
    re-checking one fixed file).  All asserts are invariants for ANY sample,
    so the fixed seeds only make the run reproducible - never flaky."""

    @staticmethod
    def _make_many_pngs(tmp_path, n):
        import io
        from PIL import Image
        web = make_game(str(tmp_path / "g"))
        for i in range(n):
            p = os.path.join(web, "img", "pictures", "rand_%03d.png" % i)
            buf = io.BytesIO()
            Image.new("RGBA", (1 + i % 8, 1 + i % 6), (i % 256, 0, 0, 255)) \
                .save(buf, "PNG")
            with open(p, "wb") as f:
                f.write(buf.getvalue())
        return web

    @staticmethod
    def _all_pngs(web):
        return sorted(glob.glob(os.path.join(web, "img", "**", "*.png"),
                                recursive=True))

    def test_png_signatures_random_sample(self, tmp_path, fake_tools):
        """Sample a random subset of a generated batch and assert the PNG
        magic directly on each sampled file; the batch must verify clean."""
        web = self._make_many_pngs(tmp_path, 40)
        all_pngs = self._all_pngs(web)
        assert len(all_pngs) >= 40
        random.seed(20260860)
        for p in random.sample(all_pngs, k=12):
            with open(p, "rb") as f:
                assert f.read(8) == b"\x89PNG\r\n\x1a\n", p
        assert verify.verify_pngs(web, workers=2) == []

    def test_verify_finds_random_corruption(self, tmp_path, fake_tools):
        """Corrupt a random subset; verify_pngs must find exactly those, and
        a random sample of the findings must still be real corruption."""
        web = self._make_many_pngs(tmp_path, 40)
        all_pngs = self._all_pngs(web)
        random.seed(20260861)
        bad_pool = set(random.sample(all_pngs, k=random.randrange(5, 15)))
        for p in bad_pool:
            with open(p, "wb") as f:
                f.write(b"BROKEN" + bytes(random.randrange(256)
                                          for _ in range(20)))
        bad = verify.verify_pngs(web, workers=1)
        assert set(bad) == bad_pool
        for p in random.sample(list(bad), k=min(5, len(bad))):
            with open(p, "rb") as f:
                assert f.read(8) != b"\x89PNG\r\n\x1a\n"
