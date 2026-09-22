"""KAG3 (.ks) -> TyranoScript project conversion.

The converter used to be one 3.9k-line module; it is split by concern here
(`docs/kirikiri-tyrano.md` §6.1 sketches the same passes as the long-term
architecture):

    tags.py      pass 0 - tag tables, corpus and engine inventories (read-only)
    scenario.py  passes 1-2 - .ks line conversion
    assets.py    pass 3 - asset name maps and media conversion
    shims.py     pass 5 - the JS/CSS shim layer (text lives in js/)
    fonts.py     font and layout injection into the output
    project.py   output assembly (engine skeleton, macros, intent report)
    cli.py       the CLI and the `convert()` orchestration

`kirikiri/convert_kag.py` stays as the historical import path and entry point,
so existing scripts and probes keep working.
"""

__all__ = ["convert", "main"]


def __getattr__(name):
    """Expose ``convert`` / ``main`` lazily (PEP 562).

    Importing `kirikiri.kag.cli` eagerly would pull in Typer for everything
    that only wants a parser (tests, probes) and makes `python -m
    kirikiri.kag.cli` warn that the submodule was already imported by the
    package.
    """
    if name in ("convert", "main"):
        from kirikiri.kag import cli
        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
