#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared RPG Maker database field-name tables.

The MZ/MV (JSON) system file stores its localized UI text under these keys;
the VX Ace (rvdata2) System object uses snake_case plural names and keeps
everything in a single combined list (no separate array list).
"""

SYSTEM_TEXT_FIELDS = ["terms", "message", "commands", "equipTypes",
                      "weaponTypes", "armorTypes", "skillTypes", "element"]
SYSTEM_TEXT_ARRAYS = ["variables", "switches"]

RVDATA2_SYSTEM_TEXT_FIELDS = ["terms", "messages", "commands", "skill_types",
                              "weapon_types", "armor_types", "elements",
                              "equip_types", "variables", "switches"]
