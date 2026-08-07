#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPG Maker -> JoiPlay conversion & compression toolkit.

Pipeline steps (run in this order on a game folder):

  build     copy web files into a JoiPlay folder (strip NW.js runtime)
  decrypt   decrypt .png_/.ogg_ assets + clear System.json encryption flags
  audio     probe + re-encode Vorbis audio (biggest size win)
  clean     remove junk files / unused fonts / unused tilesets
  verify    check PNG signatures, JSON, audio refs, System flags, key files
  serve     run an HTTP server + smoke test (for browser/JoiPlay testing)
  compress  package the result as a 7z-zstd archive (tested last)

Typical usage:
  python pipeline.py build  "path/to/game" -o out_dir
  python pipeline.py decrypt out_dir
  python pipeline.py audio   out_dir
  python pipeline.py clean   out_dir
  python pipeline.py verify  out_dir
  python pipeline.py serve   out_dir --test
  python pipeline.py compress out_dir -o out.7z
"""
import argparse
import logging
import os
import sys

from rpgmz import build, clean, compress, decrypt, detect, serve, verify
from rpgmz import audio as audio_mod
logging.basicConfig(
    level=logging.INFO,
    format="%(filename)s:%(lineno)d %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("pipeline")


def resolve_web_root(game_dir):
    wr = detect.find_web_root(game_dir)
    if not wr:
        sys.exit("ERROR: no web root found under %s (need index.html + js/)" % game_dir)
    log.info("engine: %s, web root: %s",
             "MZ" if detect.is_mz(wr) else "MV", wr)
    return wr


# ---------------------------------------------------------------- build
def cmd_build(args):
    wr = resolve_web_root(args.game)
    build.build_joiplay(wr, args.out, workers=args.workers)
    log.info("build done -> %s", args.out)


# ---------------------------------------------------------------- decrypt
def cmd_decrypt(args):
    wr = resolve_web_root(args.game)
    key = bytes.fromhex(args.key) if args.key else None
    decrypt.decrypt_and_clear(wr, key=key, workers=args.workers)


# ---------------------------------------------------------------- audio
def cmd_audio(args):
    wr = resolve_web_root(args.game)
    infos = audio_mod.probe_all(wr, sample=args.sample, workers=args.workers)
    if args.probe_only:
        audio_mod.write_probe_csv(infos, args.report)
        return
    counts, saved = audio_mod.reencode_all(wr, infos, workers=args.workers)
    if args.report:
        audio_mod.write_probe_csv(infos, args.report)


# ---------------------------------------------------------------- clean
def cmd_clean(args):
    wr = resolve_web_root(args.game)
    clean.cleanup_all(wr, dry_run=args.dry_run)


# ---------------------------------------------------------------- verify
def cmd_verify(args):
    wr = resolve_web_root(args.game)
    issues = verify.verify_all(wr, decode=args.decode, sample=args.sample,
                               source_dir=args.source)
    sys.exit(1 if issues else 0)


# ---------------------------------------------------------------- serve
def cmd_serve(args):
    wr = resolve_web_root(args.game)
    if args.test:
        _results, ok = serve.smoke_test(wr, port=args.port)
        sys.exit(0 if ok else 1)
    serve.serve(wr, port=args.port)


# ---------------------------------------------------------------- compress
def cmd_compress(args):
    wr = resolve_web_root(args.game)
    archive = args.out or (wr + ".7z")
    compress.compress(wr, archive, level=args.level)
    compress.test_archive(archive)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="copy web files into a JoiPlay folder")
    p.add_argument("game", help="source game folder")
    p.add_argument("-o", "--out", required=True, help="destination JoiPlay folder")
    p.add_argument("--workers", type=int, default=6, help="parallel copy workers")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("decrypt", help="decrypt assets + clear encryption flags")
    p.add_argument("game", help="JoiPlay folder (web root)")
    p.add_argument("--key", default=None,
                   help="explicit hex encryptionKey override (when System.json is "
                        "runtime-decrypted and hides it)")
    p.add_argument("--workers", type=int, default=8, help="parallel decrypt workers")
    p.set_defaults(func=cmd_decrypt)

    p = sub.add_parser("audio", help="probe + re-encode audio")
    p.add_argument("game", help="JoiPlay folder (web root)")
    p.add_argument("--probe-only", action="store_true", help="only probe, no encode")
    p.add_argument("--report", default="", help="write probe CSV report")
    p.add_argument("--sample", type=int, default=0, help="probe/encode only first N files")
    p.add_argument("--workers", type=int, default=4, help="parallel ffmpeg workers")
    p.set_defaults(func=cmd_audio)

    p = sub.add_parser("clean", help="remove junk/unused images and fonts")
    p.add_argument("game", help="JoiPlay folder (web root)")
    p.add_argument("--dry-run", action="store_true", help="report only, don't delete")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("verify", help="verify build integrity")
    p.add_argument("game", help="JoiPlay folder (web root)")
    p.add_argument("--decode", action="store_true", help="also full ffmpeg-decode all audio")
    p.add_argument("--sample", type=int, default=0, help="decode only first N files")
    p.add_argument("--source", default=None,
                   help="original game folder: audio refs missing there too are "
                        "warnings, not failures")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("serve", help="HTTP server + smoke test (do NOT run on phone)")
    p.add_argument("game", help="JoiPlay folder (web root)")
    p.add_argument("-p", "--port", type=int, default=8100)
    p.add_argument("--test", action="store_true",
                   help="run smoke test against key files, then exit")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("compress", help="package as 7z-zstd archive")
    p.add_argument("game", help="JoiPlay folder (web root)")
    p.add_argument("-o", "--out", default="", help="archive path (default: game folder + .7z)")
    p.add_argument("--level", type=int, default=15, help="zstd compression level (default 15)")
    p.set_defaults(func=cmd_compress)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
