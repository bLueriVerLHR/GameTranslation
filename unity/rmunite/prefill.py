"""Prefill each game's translated.json from a previous game's translations + handle character names.

Usage: python prefill.py <work_dir> <game_key> [--names names.json]

The parameter parsing lives inside main() so the module can be imported
without executing anything (this package is a set of standalone tools that
share per-game helpers).
"""
import json
import os
import re
import sys
from typing import Annotated

_HERE = os.path.dirname(os.path.abspath(__file__))
# Repo root, appended (not inserted) so a same-named sibling module in
# this directory still wins.
sys.path.append(os.path.dirname(_HERE))
from rpgmaker import cliutil  # noqa: E402


def translate_line(text, base, names):
    """Translate one key: exact base hit first, then 【Name】 prefix
    replacement (look the body up in base, replacing the name)."""
    # exact match first
    if text in base:
        return base[text]
    # [Name] prefix replacement
    m = re.match(r"^(【([^】]+)】)(.*)$", text)
    if m:
        name, rest = m.group(2), m.group(3)
        newname = names.get(name)
        if newname:
            tail = base.get(rest, rest)
            return "【" + newname + "】" + tail
    return None


def cmd(work_dir: Annotated[str, cliutil.Argument(
            help="work dir holding the series base translated.json")],
        game_key: Annotated[str, cliutil.Argument(
            help="per-game subdir name in the work dir")],
        names: Annotated[str, cliutil.Option(
            "--names", help="optional {game_key: {name: translation}} table "
            "file; without it the 【name】 prefix is left untouched")] = "",
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)

    out = os.path.abspath(work_dir)
    key = game_key
    base = json.load(open(os.path.join(out, "translated.json"), encoding="utf-8"))
    meta = json.load(open(os.path.join(out, key, "keys_target_meta.json"),
                          encoding="utf-8"))

    # character name table per game (from CharacterActorSO if present, plus
    # known series names)
    names_table = {}
    if names and os.path.exists(names):
        names_table = json.load(open(names, encoding="utf-8")).get(key, {})

    final = {}
    unresolved = []
    for k in meta:
        t = translate_line(k, base, names_table)
        if t:
            final[k] = t
        else:
            unresolved.append(k)

    with open(os.path.join(out, key, "translated_prefill.json"), "w",
              encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=1)

    print("%s: total=%d prefill=%d unresolved=%d"
          % (key, len(meta), len(final), len(unresolved)))
    with open(os.path.join(out, key, "unresolved.txt"), "w",
              encoding="utf-8") as f:
        for t in unresolved:
            f.write(t.replace("\n", "\\n") + "\n")
    return 0


# argparse showed the module docstring as the description; a single-command
# Typer app renders the command's docstring, so point it at the same text
# instead of keeping a second copy in sync.
cmd.__doc__ = __doc__

app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="prefill.py")


if __name__ == "__main__":
    raise SystemExit(main())
