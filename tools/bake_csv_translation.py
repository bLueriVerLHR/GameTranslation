#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bake_csv_translation.py - Bake a translated dict into ExternMessage.csv
(exact-match per body text; companion to build_csv_template.py and
gen_csv_shards.py).

For every data row the body is looked up in --trs; on an exact hit the body
is replaced. Bodies without a translation are left as-is. Encoding is
preserved (UTF-16LE/BOM, utf-8-sig or cp932) and CRLF line endings are kept.

Run AFTER bake_translation.py has copied the build; this tool rewrites the
CSV in place.

Usage:
    python bake_csv_translation.py <joiplay_dir> --trs <translated.json>
"""
import argparse
import csv
import io
import json
import os
import sys


def read_csv(path):
    raw = open(path, "rb").read()
    if raw[:2] == b"\xff\xfe":
        return raw.decode("utf-16"), "utf-16"
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig"), "utf-8"
    return raw.decode("cp932", errors="replace"), "cp932"


def write_csv(path, text, enc):
    if enc == "utf-16":
        data = ("\ufeff" + text).encode("utf-16-le")
    elif enc == "utf-8":
        data = ("\ufeff" + text).encode("utf-8")
    else:
        data = text.encode("cp932", errors="replace")
    with open(path, "wb") as f:
        f.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game_dir")
    ap.add_argument("--trs", required=True)
    args = ap.parse_args()

    trs = json.load(open(args.trs, encoding="utf-8"))
    csv_path = os.path.join(args.game_dir, "data", "ExternMessage.csv")
    if not os.path.exists(csv_path):
        print("no data/ExternMessage.csv; nothing to do")
        sys.exit(0)

    text, enc = read_csv(csv_path)
    rows = list(csv.reader(io.StringIO(text)))
    changed = 0
    for r in rows:
        if len(r) >= 2 and r[0].strip() and r[0].strip() != "名前":
            new = trs.get(r[1])
            if new is not None and new != r[1]:
                r[1] = new
                changed += 1
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerows(rows)
    write_csv(csv_path, out.getvalue(), enc)
    print("baked %d bodies into data/ExternMessage.csv (%s)" % (changed, enc))


if __name__ == "__main__":
    main()
