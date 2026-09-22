#!/usr/bin/env python3
"""merge_plain_chunks.py - Merge the two-file chunk format into a
translation KV dict.

For every chunks/chunk_NN.ja.txt with a matching chunk_NN.zh.txt:
  - unescape both files (plain_io: \\n = real newline, \\\\ = one backslash),
  - zip keys with their translations (line N of zh.txt = line N of ja.txt),
  - QC the pair (line count, kana left, control-code tokens, empty values,
    uncertainty markers, double backslashes),
  - merge into the output dict.

Writes <work_dir>/chunks_translated.json (default) - the agent-chunk merge
that merge_translation.py combines with prefilled hits / sweep rules into the
final translated.json.

Usage:
    python merge_plain_chunks.py <work_dir> [--out chunks_translated.json]
                                 [--strict] [--no-report]
"""
import glob
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctrl_codes  # noqa: E402
from rpgmaker import japanese as japanese_utils  # noqa: E402
import plain_io  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402
from rpgmaker import runtime  # noqa: E402

KANA = japanese_utils.KANA
UNCERTAIN = re.compile(r"【[^】]*\?[^】]*】")
ctrl_signature = ctrl_codes.ctrl_signature


def kana_left_in(v):
    """True when a value still carries translatable kana, after exempting
    Wolf RPG specifics: <>-tagged functional labels (status-name refs),
    BGM/asset paths, Woditor internal command lines, the kana-teaching UI
    (single kana char followed by a CJK ideograph), and the kana middle dot ・."""
    if KANA.search(ctrl_codes.strip_ctrl(v)) is None:
        return False
    if re.search(r"<[^>]*[\u3040-\u30ff]", v):
        return False
    if re.search(r"BGM/|\.mp3|\.ogg|\.png|WoditorEv|MapData|CommonEvent", v):
        return False
    if re.search(r"feat\.", v):
        return False  # music credits lines (artist names)
    if re.search(r"[\u3040-\u30ff][漢字汉字]", v):
        return False
    # Standalone kana (input-method teaching UI: a single kana or
    # kana-syllable row) - kept untranslated on purpose.
    if re.fullmatch(r"[\u3040-\u30ff\uff71-\uff9e]{1,4}", v.strip()):
        return False
    # Kana inside parens used as ruby / name-puzzle readings
    # (はなさない ("never let go") style): the reading itself must stay.
    if re.search(r"（[^）]*[\u3040-\u30ff][^）]*）", v):
        return False
    # Honorific / self-reference suffixes kept as the character's speech
    # quirk (俺ちゃん, ちゃん/さん/くん after a Chinese name).
    if re.search(r"俺ちゃん|[\u3040-\u30ff]*(ちゃん|さん|くん|様)$", v):
        return False
    # Strip exempt tokens, then see if any kana remains.
    body = re.sub(r"<[^>]*>", "", v)
    body = re.sub(r"[\u3040-\u30ff][漢字汉字]", "", body)
    body = body.replace("・", "")
    body = ctrl_codes.strip_ctrl(body)
    return KANA.search(body) is not None


def qc_pair(keys, vals, idx):
    """QC one chunk pair.  Returns (issues: [str], ok: bool)."""
    issues = []
    if len(keys) != len(vals):
        issues.append("line count mismatch: ja=%d zh=%d"
                      % (len(keys), len(vals)))
        return issues, False
    newline_diff = kana_left = ctrl_diff = empty = uncertain = 0
    dbl_backslash = 0
    for k, v in zip(keys, vals, strict=True):
        if not isinstance(v, str):
            continue
        if v.count("\n") != k.count("\n"):
            newline_diff += 1
        if kana_left_in(v):
            kana_left += 1
        if (sorted(ctrl_codes.CTRL_TOKEN.findall(k))
                != sorted(ctrl_codes.CTRL_TOKEN.findall(v))
                and sorted(ctrl_signature(k)) != sorted(ctrl_signature(v))):
            ctrl_diff += 1
        # Wolf RPG control codes are stored with a literal double
        # backslash (\\s[9]); a value only counts as having a stray
        # backslash when it has MORE backslashes than the key.
        if v.count("\\") > k.count("\\"):
            dbl_backslash += 1
        if UNCERTAIN.search(v):
            uncertain += 1
        if not v:
            empty += 1
    if newline_diff:
        issues.append("newline-count mismatch: %d" % newline_diff)
    if kana_left:
        issues.append("kana still in values: %d" % kana_left)
    if ctrl_diff:
        issues.append("control-code tokens differ: %d" % ctrl_diff)
    if empty:
        issues.append("empty single-line values: %d" % empty)
    if dbl_backslash:
        issues.append("double-backslash values: %d" % dbl_backslash)
    if uncertain:
        issues.append("uncertainty markers 【?】 left: %d" % uncertain)
    return issues, not issues


def _process_chunk(chunks_dir, num):
    """Load + QC one chunk.  Returns (num, keys, vals, issues, ok) or
    (num, None, None, None, False) when the zh.txt is missing.  Pure per
    chunk: no shared state, safe to run on a thread pool (review §4.2)."""
    keys, vals = plain_io.load_pair(chunks_dir, num)
    if keys is None:
        if os.path.exists(plain_io.ja_path(chunks_dir, num)):
            return num, None, None, ["zh.txt missing"], False
        return num, None, None, None, False
    issues, ok = qc_pair(keys, vals, num)
    return num, keys, vals, issues, ok


def cmd(work_dir: Annotated[str, cliutil.Argument(
            help="translation work dir (chunks/ inside it)")],
        out: Annotated[str, cliutil.Option(
            "--out", help="merged output file name, inside work_dir")] = \
        "chunks_translated.json",
        strict: Annotated[bool, cliutil.Option(
            "--strict", help="exit non-zero when any chunk has issues")] = False,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)

    work = os.path.abspath(work_dir)
    chunks_dir = os.path.join(work, "chunks")
    merged = {}
    problems = 0
    chunks = 0

    # chunk numbers in filename (glob) order - the same order the legacy
    # loop merged them, so the output dict and report lines stay identical.
    nums = []
    for p in sorted(glob.glob(os.path.join(chunks_dir, "chunk_*.ja.txt"))):
        m = re.search(r"chunk_(\d+)\.ja\.txt$", p)
        if m:
            nums.append(int(m.group(1)))

    def run(num):
        return _process_chunk(chunks_dir, num)

    if len(nums) > 1:
        # QC is CPU-ish and file-I/O bound per chunk; the pool follows the
        # machine (physical cores, see rpgmaker/runtime.py) and stays capped by
        # the chunk count, so hundreds of agent chunks cannot spawn unbounded
        # threads (review §4.2: parallelize the per-chunk QC, keep output
        # order).
        workers = min(runtime.auto_workers("qc", path=chunks_dir), len(nums))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(run, nums))
    else:
        results = [run(n) for n in nums]

    for num, keys, vals, issues, ok in results:
        if keys is None:
            if issues == ["zh.txt missing"]:
                print("chunk_%02d: zh.txt missing (not translated)" % num)
            continue
        chunks += 1
        if not ok:
            problems += 1
        merged.update(dict(zip(keys, vals, strict=True)))
        tag = "OK" if ok else "ISSUES"
        print("chunk_%02d: %d keys  [%s]%s"
              % (num, len(keys), tag,
                 ": " + "; ".join(issues) if issues else ""))

    with open(os.path.join(work, out), "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    print("merged: %d keys (%d chunks) -> %s" % (len(merged), chunks, out))
    if problems:
        print("WARN: %d/%d chunks have issues (see above)" % (problems, chunks))
        if strict:
            return 1
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="merge_plain_chunks.py")


if __name__ == "__main__":
    raise SystemExit(main())
