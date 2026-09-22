#!/usr/bin/env python3
"""Patch the translation dict so character names use consistent Chinese
transliterations.  The replacement rules are game-specific and MUST come from
an external rules file, never hardcoded here:

rules.json:
{
  "value_replacements": [["旧译", "新译"], ...],   # applied to every value, in order
  "name_keys": {"日文名": "中文名", ...}            # exact key -> canonical value
}

Replacement-order tricks (e.g. protecting a proper noun via a placeholder so a
generic rule can't mangle it) are a rule-file concern - see the example in
the docstring of gen_csv_shards.py's tone block for the general pattern.

Usage: python -m tools.patch_names <in_dict.json> <out_dict.json> [rules.json]
Writes a new JSON; the original dict is not modified.  Without rules.json the
script is a no-op (reports 0 changes).
"""
import json
import os
import sys
from typing import Annotated

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpgmaker import cliutil  # noqa: E402


def cmd(in_dict: Annotated[str, cliutil.Argument(
            help="input translation dict JSON")],
        out_dict: Annotated[str, cliutil.Argument(
            help="output JSON path (the input is never modified)")],
        rules_json: Annotated[str, cliutil.Argument(
            help="rules file; without it the run is a no-op")] = "",
        ) -> int:
    with open(in_dict, encoding="utf-8") as f:
        D = json.load(f)

    rules = {}
    if rules_json:
        with open(rules_json, encoding="utf-8") as f:
            rules = json.load(f)
    else:
        print("no rules file given - nothing to do")
        return 0

    value_replacements = rules.get("value_replacements", [])
    name_keys = rules.get("name_keys", {})

    changed = 0
    for k, v in list(D.items()):
        if not isinstance(v, str):
            continue
        new_v = v
        for old, new in value_replacements:
            new_v = new_v.replace(old, new)
        if new_v != v:
            D[k] = new_v
            changed += 1

    for k, v in name_keys.items():
        if D.get(k) != v:
            D[k] = v
            changed += 1

    with open(out_dict, "w", encoding="utf-8") as f:
        json.dump(D, f, ensure_ascii=False, indent=2)
    print("patched %d entries -> %s" % (changed, out_dict))
    return 0


app = cliutil.command_app(cmd, help=__doc__)
# Typer renders the command's own docstring for a single-command app; keep
# the module docstring visible in --help.
cmd.__doc__ = __doc__


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="patch_names.py")


if __name__ == "__main__":
    raise SystemExit(main())
