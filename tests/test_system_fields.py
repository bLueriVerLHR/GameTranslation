#!/usr/bin/env python3
"""The System.json field tables must agree across layers.

``translation.mvkeys`` decides what is extracted (and is the authority for
"what is a translatable string"); ``tools/rpgmaker_constants`` feeds the bake
and the legacy extractors.  ``tools`` may import ``translation`` but not the
other way round, so the two lists are written twice - and they drifted until
2026-09: the bake list had ``element`` instead of ``elements`` and no
``gameTitle``/``currencyUnit``, so those keys were extracted, translated and
counted as covered while the bake silently never wrote them (a real MZ build
kept a Japanese title and Japanese element names at 100% coverage).

This test is the drift alarm.
"""
import rpgmaker_constants as constants

from translation import mvkeys


def test_mz_mv_lists_cover_exactly_the_extracted_system_keys():
    # `terms` is walked separately by the extractor (it is a nested object)
    baked = set(constants.SYSTEM_TEXT_FIELDS + constants.SYSTEM_TEXT_ARRAYS)
    extracted = set(mvkeys._SYSTEM_KEYS) | {"terms"}
    assert baked == extracted, (
        f"bake-only: {sorted(baked - extracted)} / extract-only: {sorted(extracted - baked)}")


def test_no_vx_ace_field_names_leak_into_the_mz_mv_list():
    for name in ("message", "commands", "skill_types", "armor_types"):
        assert name not in constants.SYSTEM_TEXT_FIELDS


def test_names_are_the_plural_json_spelling():
    """MZ/MV JSON uses ``elements``; ``element`` silently matches nothing."""
    assert "elements" in constants.SYSTEM_TEXT_FIELDS
    assert "element" not in constants.SYSTEM_TEXT_FIELDS


def test_arrays_are_the_two_name_lists():
    assert constants.SYSTEM_TEXT_ARRAYS == ["variables", "switches"]
