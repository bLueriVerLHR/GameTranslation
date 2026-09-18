#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared RPG Maker database field-name tables.

The MZ/MV (JSON) system file stores its localized UI text under these keys;
the VX Ace (rvdata2) System object uses snake_case plural names and keeps
everything in a single combined list (no separate array list).

``SYSTEM_TEXT_FIELDS``/``SYSTEM_TEXT_ARRAYS`` must stay in step with what the
extractor collects (``translation.mvkeys._SYSTEM_KEYS`` + ``terms``) - the
extractor is the authority for "what is a translatable string", and both sides
are pinned by ``tests/test_system_fields.py``.  They drifted until 2026-09:
``elements`` was spelled ``element`` (so no element name was ever written),
``gameTitle`` and ``currencyUnit`` were missing, and the VX-Ace-only
``message``/``commands`` sat in the MZ/MV list.  The effect was silent: the
keys were extracted, translated, passed all five gates, counted in the
coverage metric - and the bake never wrote them (a real MZ build shipped a
Japanese title screen and Japanese element names at "100% coverage").
"""

SYSTEM_TEXT_FIELDS = ["terms", "gameTitle", "currencyUnit", "equipTypes",
                      "weaponTypes", "armorTypes", "skillTypes", "elements"]
SYSTEM_TEXT_ARRAYS = ["variables", "switches"]

RVDATA2_SYSTEM_TEXT_FIELDS = ["terms", "messages", "commands", "skill_types",
                              "weapon_types", "armor_types", "elements",
                              "equip_types", "variables", "switches"]
