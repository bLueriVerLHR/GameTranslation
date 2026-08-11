#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/decrypt.py RPGMV easy-decryption."""
import json
import os

from conftest import make_game

from rpgmaker import config
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
        enc = config.RPGMV_HEADER + make_encrypted_body(plain)
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
        pairs = {src: dst for src, dst in jobs}
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
            f.write(config.RPGMV_HEADER + make_encrypted_body(plain))
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
            f.write(config.RPGMV_HEADER + make_encrypted_body(plain))
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
