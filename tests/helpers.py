"""Synthetic game/media builders and portable test-tool launchers."""

import contextlib
import json
import os
import sys





def make_launcher(script_path, workdir):
    """Run scripts directly on POSIX or through a native Windows CMD shim."""
    if sys.platform != "win32":
        os.chmod(script_path, os.stat(script_path).st_mode | 0o111)
        return str(script_path)
    stem = os.path.splitext(os.path.basename(script_path))[0]
    launcher = os.path.join(workdir, stem + ".cmd")
    with open(launcher, "w", encoding="ascii", newline="\r\n") as f:
        f.write("@echo off\n")
        f.write(f'"{sys.executable}" "{script_path}" %*\n')
    return launcher



def make_png_bytes(w=1, h=1):
    """Generate a minimal valid RGBA PNG through Pillow."""
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(buf, "PNG")
    return buf.getvalue()



def write_system_json(root, encrypted=False):
    sys_json = {
        "titleBgm": {"name": "bgm1", "volume": 90, "pitch": 100, "pan": 0},
        "sounds": [{"name": "se1", "volume": 80, "pitch": 100, "pan": 0}],
        "hasEncryptedImages": encrypted,
        "hasEncryptedAudio": encrypted,
        "hasEncryptedData": encrypted,
        "encryptionKey": "0123456789abcdef0123456789abcdef" if encrypted else "",
    }
    path = os.path.join(root, "data", "System.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sys_json, f, ensure_ascii=False)


def make_game(root, mv=False, encrypted=False, with_movies=True,
              with_tilesets=True, add_junk=True):
    """Build a synthetic MZ/MV game and return its web root."""
    web = root
    if mv:
        web = os.path.join(root, "www")
        os.makedirs(web, exist_ok=True)
    for d in ("css", "data", "fonts", "js", "audio/bgm", "audio/se",
              "img/pictures", "img/tilesets", "effects", "icon"):
        os.makedirs(os.path.join(web, d), exist_ok=True)
    if with_movies:
        os.makedirs(os.path.join(web, "movies"), exist_ok=True)
    with open(os.path.join(web, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html><body>test game</body></html>\n")
    with open(os.path.join(web, "js", "main.js"), "w", encoding="utf-8") as f:
        f.write("// main\n")
    if mv:
        with open(os.path.join(web, "js", "rpg_core.js"), "w", encoding="utf-8") as f:
            f.write("// rpg_core\n")
    else:
        with open(os.path.join(web, "js", "rmmz_core.js"), "w", encoding="utf-8") as f:
            f.write("// rmmz_core\n")
        with open(os.path.join(web, "js", "rmmz_plugins.js"), "w", encoding="utf-8") as f:
            f.write("// rmmz_plugins\n")
    with open(os.path.join(web, "js", "plugins.js"), "w", encoding="utf-8") as f:
        f.write("var $plugins = [];\n")
    with open(os.path.join(web, "css", "main.css"), "w", encoding="utf-8") as f:
        f.write('@font-face { font-family: "TestFont"; src: url("used_font.ttf"); }\n')
    write_system_json(web, encrypted=encrypted)
    for fn, content in (("Map001.json", {"@name": "Map001", "events": []}),
                        ("Actors.json", [{"name": "Hero"}])):
        with open(os.path.join(web, "data", fn), "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False)
    if with_tilesets:
        with open(os.path.join(web, "data", "Tilesets.json"), "w", encoding="utf-8") as f:
            json.dump([{"tilesetNames": ["World_A1"]}], f, ensure_ascii=False)
    for rel, data in (
            ("audio/bgm/bgm1.ogg", b"O" * 100000),
            ("audio/se/se1.ogg", b"S" * 60000),
            ("audio/bgm/bgm_mono.ogg", b"M" * 70000),
            ("img/pictures/pic1.png", make_png_bytes()),
            ("img/pictures/big_pic.png", make_png_bytes(64, 48)),
            ("fonts/used_font.ttf", b"\x00\x01\x00\x00" + b"F" * 100),
            ("fonts/unused_font.otf", b"OTTO" + b"O" * 100),
            ("fonts/CaseFont.TTF", b"\x00\x01\x00\x00" + b"C" * 100)):
        with open(os.path.join(web, rel), "wb") as f:
            f.write(data)
    if with_tilesets:
        with open(os.path.join(web, "img", "tilesets", "World_A1.png"), "wb") as f:
            f.write(make_png_bytes())
        with open(os.path.join(web, "img", "tilesets", "unused.png"), "wb") as f:
            f.write(make_png_bytes())
    if add_junk:
        with open(os.path.join(web, "img", "junk.txt"), "w", encoding="utf-8") as f:
            f.write("editor leftover\n")
        with open(os.path.join(web, "img", "pictures", "junk.clip"), "w", encoding="utf-8") as f:
            f.write("clip\n")
    # Desktop runtime files must be stripped by build, never copied.
    for fn in ("Game.exe", "nw.dll", "icudtl.dat"):
        with open(os.path.join(root, fn), "wb") as f:
            f.write(b"NWJS" * 10)
    return web


def fs_is_case_sensitive(path):
    """Report whether the filesystem distinguishes file-name case."""
    probe = os.path.join(str(path), "CaseProbe")
    with open(probe, "w", encoding="ascii") as f:
        f.write("x")
    try:
        return not os.path.exists(os.path.join(str(path), "caseprobe"))
    finally:
        with contextlib.suppress(OSError):
            os.remove(probe)

