#!/usr/bin/env python3
"""TyranoScript / TyranoBuilder -> JoiPlay conversion pipeline (CLI wrapper).

The commands live in `rpgmaker/cli.py` (built with Typer) and share the
serve/compress/deliver implementations with the RPG Maker pipeline.  This
file only keeps the documented invocation
`python tyrano/pipeline.py <command> ...` working; run it with `--help` for
the full list.
"""

from rpgmaker.cli import tyrano_main

if __name__ == "__main__":
    tyrano_main()
