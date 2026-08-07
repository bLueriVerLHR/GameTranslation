#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_csv_template.py - Extract ExternMessage.csv dialogue into a
translation work package (for the static-subagent workflow, docs/translation.md).

The ExternMessage.js plugin stores dialogue in `data/ExternMessage.csv`
(rows: 名前(ID),本文(body),...), referenced from events via \\M[ID]. This tool
produces, in <work_dir>:

  csv_template.json   { body_text: "" }  deduplicated translatable bodies
  csv_meta.json       rows list (id, body, translatable flag) for the baker

Bodies consisting only of directives (\\M[..], :name[..], :bg[..], :layout[..],
:face[..], whitespace) are marked non-translatable (identity) and excluded
from the template. Only `ExternMessage.csv` is read (the plugin loads one CSV,
path from its "Csv File Path" parameter).

Usage:
    python build_csv_template.py <game_dir> <work_dir>
"""
import csv
import io
import json
import os
import re
import sys

DIRECTIVE_RE = re.compile(
    r"\\M\[[^\]]*\]|:name\[[^\]]*\]|:bg\[[^\]]*\]|:layout\[[^\]]*\]"
    r"|:face\[[^\]]*\]|\\V\[[^\]]*\]|\\C\[[^\]]*\]"
)
JP_TEXT_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def read_csv(path):
    raw = open(path, "rb").read()
    if raw[:2] == b"\xff\xfe":
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig")
    return raw.decode("cp932", errors="replace")


def has_text(body):
    rest = DIRECTIVE_RE.sub("", body)
    return bool(JP_TEXT_RE.search(rest))


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    game, work = sys.argv[1], sys.argv[2]
    csv_path = os.path.join(game, "data", "ExternMessage.csv")
    if not os.path.exists(csv_path):
        print("no data/ExternMessage.csv; nothing to do")
        sys.exit(0)
    os.makedirs(work, exist_ok=True)

    rows = list(csv.reader(io.StringIO(read_csv(csv_path))))
    bodies = {}
    meta = []
    for r in rows:
        if len(r) < 2:
            continue
        row_id, body = r[0].strip(), r[1]
        if not row_id or row_id == "名前":
            continue
        if not body.strip():
            continue
        translatable = has_text(body)
        meta.append({"id": row_id, "body": body, "text": translatable})
        if translatable:
            bodies.setdefault(body, row_id)

    tpl = {k: "" for k in bodies}
    with open(os.path.join(work, "csv_template.json"), "w",
              encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False, indent=1)
    with open(os.path.join(work, "csv_meta.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("csv rows: %d  translatable bodies: %d (unique: %d)  identity: %d"
          % (len(meta), sum(1 for m in meta if m["text"]),
             len(tpl), sum(1 for m in meta if not m["text"])))


if __name__ == "__main__":
    main()
