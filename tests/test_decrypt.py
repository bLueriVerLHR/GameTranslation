#!/usr/bin/env python3
"""Unit tests for rpgmaker/decrypt.py RPGMV easy-decryption."""
import json
import os
import random

from conftest import make_game

from rpgmaker import constants
from rpgmaker import decrypt as dec


KEY = bytes.fromhex("0123456789abcdef0123456789abcdef")
KEY_HEX = KEY.hex()


def make_encrypted_body(plaintext, key=KEY):
    body = bytearray(plaintext)
    for i in range(min(16, len(body))):
        body[i] ^= key[i]
    return bytes(body)


class TestDecryptCore:
    def test_decrypt_to(self, tmp_path):
        plain = b"PNG-PLAINTEXT-DATA" + b"\x00" * 32
        enc = constants.RPGMV_HEADER + make_encrypted_body(plain)
        src = tmp_path / "a.png_"
        src.write_bytes(enc)
        dst = tmp_path / "a.png"
        assert dec._decrypt_to(str(src), KEY, str(dst)) is True
        assert dst.read_bytes() == plain
        assert not src.exists()

    def test_decrypt_to_no_header_left_alone(self, tmp_path):
        src = tmp_path / "b.png_"
        src.write_bytes(b"\x00" * 32)
        dst = tmp_path / "b.png"
        assert dec._decrypt_to(str(src), KEY, str(dst)) is False
        assert src.exists()
        assert not dst.exists()

    def test_decrypt_to_short_file(self, tmp_path):
        src = tmp_path / "c.png_"
        src.write_bytes(b"\x01")
        assert dec._decrypt_to(str(src), KEY, str(tmp_path / "c.png")) is False

    def test_mv_ext_mapping(self):
        assert dec.MV_EXT_TO_STANDARD[".rpgmvp"] == ".png"
        assert dec.MV_EXT_TO_STANDARD[".rpgmvo"] == ".ogg"
        assert dec.MV_EXT_TO_STANDARD[".rpgmvm"] == ".webm"


class TestEncryptedFileIteration:
    def test_mz_underscore_and_mv_forms(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        img = os.path.join(web, "img", "pictures")
        (tmp_path / "h.png_").write_bytes(b"x")  # not under web root
        p1 = os.path.join(img, "pic_.png_")
        with open(p1, "wb") as f:
            f.write(b"x")
        mv = os.path.join(web, "img", "faces")
        os.makedirs(mv)
        p2 = os.path.join(mv, "f.rpgmvp")
        with open(p2, "wb") as f:
            f.write(b"x")
        jobs = list(dec._iter_encrypted_files(web))
        pairs = dict(jobs)
        assert p1 in pairs and pairs[p1] == os.path.join(img, "pic_.png")
        assert p2 in pairs and pairs[p2] == os.path.join(mv, "f.png")


class TestSystemJson:
    def test_load_key(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        with open(os.path.join(web, "data", "System.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"encryptionKey": KEY_HEX}, f)
        assert dec.load_encryption_key(web) == KEY

    def test_load_key_missing(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        with open(os.path.join(web, "data", "System.json"), "w",
                  encoding="utf-8") as f:
            json.dump({}, f)
        assert dec.load_encryption_key(web) is None

    def test_load_key_bad_hex(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        with open(os.path.join(web, "data", "System.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"encryptionKey": "zz"}, f)
        assert dec.load_encryption_key(web) is None

    def test_clear_encryption_flags(self, tmp_path):
        web = make_game(str(tmp_path / "g"), encrypted=True)
        dec.clear_encryption_flags(web)
        with open(os.path.join(web, "data", "System.json"), encoding="utf-8-sig") as f:
            s = json.load(f)
        assert s["hasEncryptedImages"] is False
        assert s["encryptionKey"] == ""
        with open(os.path.join(web, "data", "System.json"), "rb") as f:
            assert f.read(3) != b"\xef\xbb\xbf"  # no BOM

    def test_clear_flags_non_json_touches_nothing(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        p = os.path.join(web, "data", "System.json")
        with open(p, "wb") as f:
            f.write(b"\xde\xad\xbe\xef")
        dec.clear_encryption_flags(web)
        with open(p, "rb") as f:
            assert f.read() == b"\xde\xad\xbe\xef"


class TestTreeDecrypt:
    def test_easy_decrypt_and_clear(self, tmp_path):
        root = str(tmp_path / "g")
        web = make_game(root, encrypted=True)
        plain = b"SECRET-PICTURE" + b"\x00" * 40
        enc_path = os.path.join(web, "img", "pictures", "secret.png_")
        with open(enc_path, "wb") as f:
            f.write(constants.RPGMV_HEADER + make_encrypted_body(plain))
        d, s = dec.decrypt_and_clear(web)
        assert d == 1 and s == 0
        with open(os.path.join(web, "img", "pictures", "secret.png"), "rb") as f:
            assert f.read() == plain
        assert not os.path.exists(enc_path)
        with open(os.path.join(web, "data", "System.json"), encoding="utf-8-sig") as f:
            sysj = json.load(f)
        assert sysj["hasEncryptedImages"] is False

    def test_complex_kept_flags_kept(self, tmp_path):
        web = make_game(str(tmp_path / "g"), encrypted=True)
        enc_path = os.path.join(web, "img", "pictures", "weird.png_")
        with open(enc_path, "wb") as f:
            f.write(b"\x00" * 32)  # no RPGMV header -> custom encryption
        d, s = dec.decrypt_and_clear(web)
        assert d == 0 and s == 1
        assert os.path.exists(enc_path)
        with open(os.path.join(web, "data", "System.json"), encoding="utf-8-sig") as f:
            sysj = json.load(f)
        assert sysj["hasEncryptedImages"] is True

    def test_no_key_nothing_to_do(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        d, s = dec.decrypt_and_clear(web)
        assert d == 0 and s == 0

    def test_data_encrypted_folder(self, tmp_path):
        web = make_game(str(tmp_path / "g"), encrypted=True)
        src = os.path.join(web, "data_encrypted")
        os.makedirs(src)
        plain = b'{"events":[]}' + b"\x00" * 16
        with open(os.path.join(src, "Map001.json_"), "wb") as f:
            f.write(constants.RPGMV_HEADER + make_encrypted_body(plain))
        d, kept = dec.decrypt_data_encrypted(web, KEY)
        assert d == 1 and kept == 0
        with open(os.path.join(web, "data", "Map001.json"), "rb") as f:
            assert f.read() == plain
        assert not os.path.isdir(src)

    def test_data_encrypted_custom_kept(self, tmp_path):
        web = make_game(str(tmp_path / "g"), encrypted=True)
        src = os.path.join(web, "data_encrypted")
        os.makedirs(src)
        with open(os.path.join(src, "Map001.json"), "wb") as f:
            f.write(b"\xde\xad\xbe\xef")
        d, kept = dec.decrypt_data_encrypted(web, KEY)
        assert d == 0 and kept == 1
        assert os.path.isdir(src)


class TestRandomSampleDecrypt:
    """Random-sampled encrypted assets must decrypt to valid PNG/OGG magic.

    AGENTS.md task-rule 4 (mandatory): batch quality checks sample randomly
    instead of always re-checking one known-good file.  Every assert below is
    an invariant that must hold for ANY sampled file, so a fixed seed (or a
    varying one) never makes the test flaky.
    """

    PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
    OGG_MAGIC = b"OggS"

    @staticmethod
    def _xor_body(plain, key):
        body = bytearray(plain)
        for i in range(min(16, len(body))):
            body[i] ^= key[i]
        return bytes(body)

    @staticmethod
    def _build_pool(rng, n):
        """n random (src_rel, dst_rel, plaintext, magic) encrypted resources:
        a mix of MZ (_) and MV (.rpgmvp/.rpgmvo) forms, PNG and OGG."""
        pool = []
        for i in range(n):
            kind = i % 4
            if kind == 0:
                ext, dst_ext = ".png_", ".png"
            elif kind == 1:
                ext, dst_ext = ".ogg_", ".ogg"
            elif kind == 2:
                ext, dst_ext = ".rpgmvp", ".png"
            else:
                ext, dst_ext = ".rpgmvo", ".ogg"
            magic = (TestRandomSampleDecrypt.PNG_MAGIC if i % 2 == 0
                     else TestRandomSampleDecrypt.OGG_MAGIC)
            folder = "img/pictures" if ext in (".png_", ".rpgmvp") else "audio/bgm"
            body = magic + bytes(rng.randrange(256)
                                 for _ in range(rng.randrange(16, 96)))
            src_rel = os.path.join(folder, "rand_%02d%s" % (i, ext))
            dst_rel = os.path.join(folder, "rand_%02d%s" % (i, dst_ext))
            pool.append((src_rel, dst_rel, body, magic))
        return pool

    def test_random_sample_decrypted_headers(self, tmp_path):
        """Decrypt a whole batch, then randomly sample a subset and assert
        every sampled file round-trips to its exact plaintext + magic."""
        rng = random.Random(20260817)
        web = make_game(str(tmp_path / "g"), encrypted=True)
        key = bytes(rng.randrange(256) for _ in range(16))
        with open(os.path.join(web, "data", "System.json"),
                  encoding="utf-8-sig") as f:
            s = json.load(f)
        s["encryptionKey"] = key.hex()
        with open(os.path.join(web, "data", "System.json"), "w",
                  encoding="utf-8") as f:
            json.dump(s, f)

        pool = self._build_pool(rng, 40)
        for src_rel, _dst_rel, body, _magic in pool:
            path = os.path.join(web, src_rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(constants.RPGMV_HEADER + self._xor_body(body, key))

        decrypted, skipped = dec.decrypt_and_clear(web)
        assert (decrypted, skipped) == (40, 0)

        for src_rel, dst_rel, body, magic in rng.sample(pool, k=12):
            with open(os.path.join(web, dst_rel), "rb") as f:
                got = f.read()
            assert got == body
            assert got[:len(magic)] == magic
            assert not os.path.exists(os.path.join(web, src_rel))

        with open(os.path.join(web, "data", "System.json"),
                  encoding="utf-8-sig") as f:
            s = json.load(f)
        assert s["hasEncryptedImages"] is False
        assert s["hasEncryptedAudio"] is False
        assert s["encryptionKey"] == ""

    def test_random_sample_custom_encrypted_kept(self, tmp_path):
        """Sampled resources that lack the RPGMV header (custom/plugin
        encryption) must be left untouched and counted as skipped."""
        rng = random.Random(20260818)
        web = make_game(str(tmp_path / "g"), encrypted=True)
        pool = []
        for i in range(20):
            magic = self.PNG_MAGIC if i % 2 == 0 else self.OGG_MAGIC
            body = magic + bytes(rng.randrange(256) for _ in range(24))
            src_rel = os.path.join("img/pictures", "custom_%02d.png_" % i)
            dst_rel = os.path.join("img/pictures", "custom_%02d.png" % i)
            pool.append((src_rel, dst_rel, body))
            path = os.path.join(web, src_rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(body)  # valid asset body but NO RPGMV header

        decrypted, skipped = dec.decrypt_and_clear(web, key=KEY)
        assert (decrypted, skipped) == (0, 20)
        for src_rel, dst_rel, body in rng.sample(pool, k=8):
            with open(os.path.join(web, src_rel), "rb") as f:
                assert f.read() == body
            assert not os.path.exists(os.path.join(web, dst_rel))
        # complex game: flags must NOT be cleared
        with open(os.path.join(web, "data", "System.json"),
                  encoding="utf-8-sig") as f:
            s = json.load(f)
        assert s["hasEncryptedImages"] is True
        assert s["hasEncryptedAudio"] is True

    def test_random_sample_data_encrypted(self, tmp_path):
        """Randomly sampled data_encrypted files decrypt into data/ with the
        exact original JSON bytes (incl. short [] edge case)."""
        rng = random.Random(20260819)
        web = make_game(str(tmp_path / "g"), encrypted=True)
        src = os.path.join(web, "data_encrypted")
        os.makedirs(src)
        plans = []
        for i in range(12):
            body = (b'{"events":[]}' if i % 3 == 0 else
                    (b'[]' if i % 3 == 1 else b'{"a":1}'))
            plans.append(("Map%03d.json_" % i, body))
            with open(os.path.join(src, "Map%03d.json_" % i), "wb") as f:
                f.write(constants.RPGMV_HEADER + self._xor_body(body, KEY))
        d, kept = dec.decrypt_data_encrypted(web, KEY)
        assert (d, kept) == (12, 0)
        for fn, body in rng.sample(plans, k=5):
            with open(os.path.join(web, "data", fn[:-1]), "rb") as f:
                assert f.read() == body
        assert not os.path.isdir(src)
