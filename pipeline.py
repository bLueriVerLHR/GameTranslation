#!/usr/bin/env python3
"""RPG Maker MZ/MV -> JoiPlay conversion & compression toolkit (CLI wrapper).

The commands live in `rpgmaker/cli.py` (built with Typer); this file only
keeps the documented invocation `python pipeline.py <command> ...` working.
Run `python pipeline.py --help` for the full list.
"""
from rpgmaker.cli import main

if __name__ == "__main__":
    main()
