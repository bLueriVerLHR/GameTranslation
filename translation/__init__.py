#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""translation - the v2 translation workflow toolkit (one subagent, one game).

Design: `.tmp/TRANSLATION_WORKFLOW_V2.md`.  Shape of the system:

  * the parent (orchestrator) owns the *mechanical* half: extract a flat,
    story-ordered key list, derive the control-code table from the game itself,
    turn the subagent's raw text library into JSON, run the four hard gates and
    bake.  Nothing here makes a language decision.
  * the translation subagent owns the *semantic* half: name drafts, scene
    summaries, tone, the translations themselves, and the rewrite decisions.

Module map:

  ``codes``      control-code parsing + inventory derived from the game's JS
  ``mvkeys``     story-ordered key extraction (RPG Maker MV / MZ data trees)
  ``rawlib``     raw translation library IO, rewrites, the four gates
  ``workspace``  workspace skeleton + the subagent's MISSION (hard protocol)
  ``cli``        one Typer app over all of the above
"""

__all__ = ["codes", "mvkeys", "rawlib", "workspace"]
