"""clean_kana_ticks.py - Final tick cleanup: convert residual kana
mouth-sounds OUTSIDE \\RB[] codes to Chinese/romaji so the shipped build has
~zero kana. \\RB[正文,注音] ruby args are converted by convert_rb_ruby.py;
author/plugin/name values are exempt (see the local word table, docs/translation.md §6).

Usage:
    python tools\\clean_kana_ticks.py <merged.json> [--exempt <file>]
"""
import json
import os
import re
import sys
from typing import Annotated

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rpgmaker import japanese as japanese_utils  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402

KANA_ALL = japanese_utils.KANA_PURE_WORD
KANA = japanese_utils.KANA

TAIL_RULES = [
    (re.compile(r"ッッッ+$"), "!!!"),
    (re.compile(r"ッッ$"), "!!"),
    (re.compile(r"ッ$"), "!"),
    (re.compile(r"っっっ+$"), "!!!"),
    (re.compile(r"っっ$"), "!!"),
    (re.compile(r"っ$"), ""),
    (re.compile(r"ぁぁぁ+$"), "啊——"),
    (re.compile(r"ぁぁ$"), "啊——"),
    (re.compile(r"ぁ$"), "啊"),
    (re.compile(r"ぉぉぉ+$"), "哦——"),
    (re.compile(r"ぉぉ$"), "哦——"),
    (re.compile(r"ぉ$"), "哦"),
    (re.compile(r"ぅぅぅ+$"), "呜——"),
    (re.compile(r"ぅぅ$"), "呜——"),
    (re.compile(r"ぅ$"), "呜"),
    (re.compile(r"ぃぃぃ+$"), "咿——"),
    (re.compile(r"ぃぃ$"), "咿——"),
    (re.compile(r"ぃ$"), "咿"),
    (re.compile(r"ぇぇぇ+$"), "诶——"),
    (re.compile(r"ぇぇ$"), "诶——"),
    (re.compile(r"ぇ$"), "诶"),
    (re.compile(r"ォォォ+$"), "哦——"),
    (re.compile(r"ォォ$"), "哦——"),
    (re.compile(r"ォ$"), "哦"),
    (re.compile(r"ィィィ+$"), "咿——"),
    (re.compile(r"ィィ$"), "咿——"),
    (re.compile(r"ィ$"), "咿"),
    (re.compile(r"ゥゥゥ+$"), "呜——"),
    (re.compile(r"ゥゥ$"), "呜——"),
    (re.compile(r"ゥ$"), "呜"),
    (re.compile(r"ャャ+$"), "呀——"),
    (re.compile(r"ャ$"), "呀"),
    (re.compile(r"ュュ+$"), "哟——"),
    (re.compile(r"ュ$"), "哟"),
    (re.compile(r"ョョ+$"), "哟——"),
    (re.compile(r"ョ$"), "哟"),
    (re.compile(r"ヮ$"), "哇"),
    (re.compile(r"んん+$"), "嗯嗯"),
    (re.compile(r"ん$"), "嗯"),
    (re.compile(r"ンン+$"), "嗯嗯"),
    (re.compile(r"ン$"), "嗯"),
]

MID_RULES = [
    (re.compile(r"ッ"), "!"),
    (re.compile(r"っ"), ""),
    (re.compile(r"ぁ"), "啊"),
    (re.compile(r"ぉ"), "哦"),
    (re.compile(r"ぅ"), "呜"),
    (re.compile(r"ぃ"), "咿"),
    (re.compile(r"ぇ"), "诶"),
    (re.compile(r"ォ"), "哦"),
    (re.compile(r"ィ"), "咿"),
    (re.compile(r"ゥ"), "呜"),
    (re.compile(r"ン"), "嗯"),
    (re.compile(r"ん"), "嗯"),
]

TAG = re.compile(r"<[^>]*>")
RB = re.compile(r"\\RB\[[^\]]*\]")
IF = re.compile(r"if\([^)]*\)|:name(?:\[[^\]]*\])?|[A-Za-z]+://\S+")
CJK = re.compile(r"[\u4e00-\u9fff]")
# Author/brand names are exempt from tick-cleaning.  Do NOT hardcode
# per-game names here (game-specific pollution, same class as the old
# hardcoded tone bug) - pass them via --exempt <file> (one per line).
AUTHOR_NAMES = set()


def is_authorish(k, v):
    if v.strip() in AUTHOR_NAMES:
        return True
    return bool(len(v) <= 40 and not CJK.search(v) and KANA_ALL.match(v.strip()))


def clean_plain(seg):
    """seg has no \\RB codes (already split out). Apply tail rules per line
    and mid rules; skip pure-kana words."""
    lines = seg.split("\n")
    new_lines = []
    for ln in lines:
        stripped = ln.strip()
        # pure kana word (author/onomatopoeia standalone) -> keep
        if stripped and KANA_ALL.match(stripped) and len(stripped) <= 20:
            new_lines.append(ln)
            continue
        for rx, rep in TAIL_RULES:
            ln = rx.sub(rep, ln)
        for rx, rep in MID_RULES:
            ln = rx.sub(rep, ln)
        ln = ln.replace("゛", "").replace("゜", "")
        new_lines.append(ln)
    return "\n".join(new_lines)


def clean_value(k, v):
    if is_authorish(k, v):
        return v
    out = []
    pos = 0
    for m in re.finditer(r"\\RB\[[^\]]*\]|<[^>]*>|if\([^)]*\)|:name(?:\[[^\]]*\])?", v):
        out.append(clean_plain(v[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(clean_plain(v[pos:]))
    return "".join(out)


def cmd(merged_json: Annotated[str, cliutil.Argument(
            help="merged translated.json to clean in place")],
        exempt: Annotated[str, cliutil.Option(
            "--exempt", help="extra author/name values file (one per line)")] = "") -> int:
    P = os.path.abspath(merged_json)
    global AUTHOR_NAMES
    if exempt:
        for line in open(exempt, encoding="utf-8"):
            line = line.strip()
            if line:
                AUTHOR_NAMES.add(line)

    data = json.load(open(P, encoding="utf-8"))
    n = 0
    for k, v in data.items():
        nv = clean_value(k, v)
        if nv != v:
            data[k] = nv
            n += 1
    json.dump(data, open(P, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("cleaned values:", n)

    # verify: kana outside RB/tags/author-names
    left = []
    for k, v in data.items():
        v2 = re.sub(r"\\RB\[[^\]]*\]|<[^>]*>", "", v)
        if KANA.search(v2):
            left.append((k, v))
    print("kana outside exempt classes:", len(left))
    for k, v in left[:30]:
        print("K:", repr(k)[:55])
        print("V:", repr(v)[:70])
    return 0


app = cliutil.command_app(cmd, help=__doc__)
# argparse used the module docstring as the command description; keep that
# visible in --help (a collapsed single-command app shows the command help).
cmd.__doc__ = __doc__


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="clean_kana_ticks.py")


if __name__ == "__main__":
    raise SystemExit(main())
