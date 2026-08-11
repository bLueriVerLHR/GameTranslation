#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clean a built TyranoScript folder: MTool residues, junk and desktop
runtime leftovers.

MTool leaves a translation dictionary, launch/remove scripts and a hook
dll in the game root; none of it is referenced by the game's own
index.html, so it is deleted.  Everything is verified against references
before removal.
"""
import logging
import os

log = logging.getLogger("tyrano.clean")

# MTool injection residues (root level).  The dictionary json is only
# removed when no file under the folder references it.
MTool_HOOKS = ("winmm.dll", "version.dll")
MTool_SCRIPTS = ("与工具一同启动.bat", "从游戏中移除工具文件.bat",
                 "启动游戏.bat", "移除工具文件.bat")
MTool_NAMES = ("MTool挂载翻译.txt", "MTool_Config.exe", "MTool_Game.exe",
               "MTool_Game.exe_LAA_BAK")
# Runtime dictionaries written by MTool into the game root (name is the
# game title).  Removal is ref-checked too.
SAV_RESIDUES = ("_sf.sav", "_tyrano_data.sav")


def _referenced(root, name):
    """True when any file under root references the given filename."""
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            if fn == name:
                continue
            path = os.path.join(dp, fn)
            try:
                with open(path, "rb") as f:
                    chunk = f.read(1 << 20)
            except OSError:
                continue
            if name.encode("utf-8", "ignore") in chunk:
                return True
    return False


def _remove(path, what, stats):
    if os.path.isdir(path) and not os.path.islink(path):
        import shutil
        shutil.rmtree(path)
    else:
        os.remove(path)
    stats.append(what)
    log.info("removed %s", what)


def cleanup_all(web_root, dry_run=False):
    """Remove residues; returns the list of removed paths (relative)."""
    removed = []
    root = web_root

    for name in list(os.listdir(root)):
        path = os.path.join(root, name)
        is_dir = os.path.isdir(path) and not os.path.islink(path)
        # MTool hook dlls / launch scripts: never referenced by the game.
        if (name.lower() in MTool_HOOKS
                or name in MTool_SCRIPTS
                or name in MTool_NAMES
                or (is_dir and name.lower() in ("injectpath",))):
            if not dry_run:
                _remove(path, os.path.join(root, name), removed)
            else:
                removed.append(os.path.join(root, name))
            continue
        # Root-level save files MTool wrote next to the game.
        if os.path.isfile(path) and name.endswith(SAV_RESIDUES):
            if not dry_run:
                _remove(path, os.path.join(root, name), removed)
            else:
                removed.append(os.path.join(root, name))
            continue
        # Root-level runtime translation dictionary json (title-named),
        # only when the game never references it.
        if (os.path.isfile(path) and name.endswith(".json")
                and not name.lower().endswith(("package.json",))
                and not _referenced(root, name)):
            if not dry_run:
                _remove(path, os.path.join(root, name), removed)
            else:
                removed.append(os.path.join(root, name))

    log.info("clean: %d items removed (dry_run=%s)", len(removed), dry_run)
    return removed


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("web_root")
    ap.add_argument("--dry-run", action="store_true",
                    help="only report what would be removed")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    for p in cleanup_all(args.web_root, dry_run=args.dry_run):
        print(p)


if __name__ == "__main__":
    main()
