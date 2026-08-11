#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TyranoScript / TyranoBuilder -> JoiPlay conversion pipeline.

Steps (run in this order on a game folder):

  build     unpack resources/app.asar into a JoiPlay HTML5 folder,
            strip the Electron runtime, fix the save backend (webstorage)
  audio     re-encode bgm/ + sound/ mp3 to Ogg Vorbis and rewrite the
            scenario .ks audio refs in lockstep
  clean     remove MTool residues and other desktop leftovers
  fix-autoplay
            patch kag.tag_ext.js so [bgmovie] starts despite the browser
            autoplay policy (idempotent; games without bgmovie are a no-op)
  verify    check layout, save backend, audio refs and PNG limits
  serve     run an HTTP server + smoke test (for browser/JoiPlay testing)
  compress  package the result as a 7z-zstd archive (tested last)
  deliver   compress locally, copy the archive to the archives dir,
            then extract it into the games dir (replaces the old copy step)

The serve/compress/deliver steps are shared with the RPG Maker pipeline
(rpgmaker/serve.py etc. are engine-agnostic).

Typical usage:
  python3 tyrano/pipeline.py build   "path/to/game" -o out_dir
  python3 tyrano/pipeline.py audio    out_dir
  python3 tyrano/pipeline.py clean    out_dir
  python3 tyrano/pipeline.py verify   out_dir
  python3 tyrano/pipeline.py serve    out_dir --test
  python3 tyrano/pipeline.py compress out_dir -o out.7z
  python3 tyrano/pipeline.py deliver  out_dir
"""
import argparse
import logging
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpgmaker import compress as rpg_compress  # noqa: E402
from rpgmaker import deliver as rpg_deliver  # noqa: E402
from rpgmaker import serve as rpg_serve  # noqa: E402

from tyrano import audio as audio_mod  # noqa: E402
from tyrano import autoplay as autoplay_mod  # noqa: E402
from tyrano import build as build_mod  # noqa: E402
from tyrano import clean as clean_mod  # noqa: E402
from tyrano import verify as verify_mod  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(filename)s:%(lineno)d %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("tyrano.pipeline")

SMOKE_PATHS = ["index.html", "tyrano/tyrano.js", "data/scenario/first.ks",
               "data/system/Config.tjs"]


def cmd_build(args):
    build_mod.build(args.game, args.out, asar_path=args.asar)
    log.info("build done -> %s", args.out)


def cmd_audio(args):
    counts = audio_mod.convert(args.out, workers=args.workers,
                               keep=args.keep, sample=args.sample)
    log.info("audio done: %s", counts)


def cmd_clean(args):
    removed = clean_mod.cleanup_all(args.out, dry_run=args.dry_run)
    for p in removed:
        log.info("removed %s", p)


def cmd_fix_autoplay(args):
    autoplay_mod.patch_autoplay(args.out)


def cmd_verify(args):
    problems = verify_mod.verify(args.out, source=args.source,
                                 check_png=not args.no_png)
    for p in problems:
        log.error("verify: %s", p)
    if problems:
        raise SystemExit(1)


def _smoke_test(folder, port, host="127.0.0.1"):
    """Start server, request key files, report status codes, stop server."""
    srv, _t = rpg_serve.start_server(folder, port, host)
    results = {}
    try:
        base = "http://%s:%d" % (host, port)
        paths = list(SMOKE_PATHS)
        # one real ogg + one real png for a concrete asset check
        for sub in ("data/bgm", "data/sound"):
            d = os.path.join(folder, sub)
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if fn.endswith(".ogg"):
                        paths.append(sub + "/" + fn)
                        break
        for path in dict.fromkeys(paths):
            url = base + "/" + urllib.parse.quote(path)
            try:
                with urllib.request.urlopen(url, timeout=10) as r:
                    results[path] = r.status
            except Exception as e:
                results[path] = str(e)
    finally:
        rpg_serve.stop_server(srv)
    ok = bool(results) and all(v == 200 for v in results.values())
    log.info("smoke test: %s", "ALL 200 OK" if ok else "ISSUES")
    for k, v in results.items():
        log.info("  %-45s %s", k, v)
    return ok


def cmd_serve(args):
    if args.test:
        if not _smoke_test(args.out, args.port):
            raise SystemExit(1)
        log.info("smoke test OK")
        return
    srv, _t = rpg_serve.start_server(args.out, port=args.port)
    log.info("serving at http://127.0.0.1:%d (Ctrl+C to stop)", args.port)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def cmd_compress(args):
    archive = args.archive or args.out + ".7z"
    out = rpg_compress.compress(args.out, archive, level=args.level)
    rpg_compress.test_archive(out)
    log.info("compressed -> %s", out)


def cmd_deliver(args):
    rpg_deliver.deliver(args.out, archive=args.archive)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="unpack asar + prepare JoiPlay folder")
    p.add_argument("game", help="original game folder (contains resources/app.asar)")
    p.add_argument("-o", "--out", default=None, help="output folder")
    p.add_argument("--asar", default=None,
                   help="path to app.asar (absolute, or relative to game)")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("audio", help="mp3 -> ogg + rewrite script refs")
    p.add_argument("out", help="built game folder")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--keep", action="store_true", help="keep original mp3")
    p.add_argument("--sample", type=int, default=None,
                   help="convert at most N files (trial run)")
    p.set_defaults(func=cmd_audio)

    p = sub.add_parser("clean", help="remove MTool residues / junk")
    p.add_argument("out", help="built game folder")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("fix-autoplay",
                       help="patch [bgmovie] play() with user-interaction "
                            "fallback (autoplay policy)")
    p.add_argument("out", help="built game folder")
    p.set_defaults(func=cmd_fix_autoplay)

    p = sub.add_parser("verify", help="check the built folder")
    p.add_argument("out", help="built game folder")
    p.add_argument("--source", default=None, help="original game folder")
    p.add_argument("--no-png", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("serve", help="HTTP server + smoke test")
    p.add_argument("out", help="built game folder")
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--test", action="store_true", help="smoke test then exit")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("compress", help="7z-zstd package")
    p.add_argument("out", help="built game folder")
    p.add_argument("-o", "--archive", default=None, help="output .7z path")
    p.add_argument("--level", type=int, default=15)
    p.set_defaults(func=cmd_compress)

    p = sub.add_parser("deliver", help="write back to the storage side")
    p.add_argument("out", help="built game folder")
    p.add_argument("--archive", default=None,
                   help="archive name in the archives dir (default: folder name)")
    p.set_defaults(func=cmd_deliver)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
