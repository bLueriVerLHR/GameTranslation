#!/usr/bin/env python3
"""Unit tests for tools/gen_completion_shards.py - the completion-pass shard
generator (residual text, story order).

Contract under test (docs/translation.md + the chunk contract in AGENTS.md):
- every chunk gets chunk_NN.ja.txt (keys only, plain_io escaping),
  chunk_NN.context.md (rules + tone + carry-over + scene transcript) and
  chunk_NN.meta.json (which maps the chunk spans);
- the ja.txt line count IS the contract the translating agent works against
  (zh.txt must have the same line count / order), so it must equal the key
  count, and a chunk already translated by an agent must survive a re-run:
  this generator never writes or clears chunk_NN.zh.txt;
- tone comes from the game package (<work>/tone.md or --tone); a missing or
  empty tone falls back to the neutral block and never crashes;
- keys are partitioned in story order without loss or duplication, and every
  chunk stays inside --max-chars unless a single key is longer than the cap;
- glossary candidates are harvested from the MTool dict, filtered, and only
  injected into the chunks that actually contain the term.
"""
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import gen_completion_shards as gcs  # noqa: E402
import gen_translation_shards as gts  # noqa: E402
import plain_io  # noqa: E402

WHERE = "Map001.json#ev0#pg0#c1"
NEUTRAL_MARKER = "## Tone (from the game owner)"
CUSTOM_TONE = "TONE-MARKER: calm narrator, short lines"


def write_json(path, data, bom=False):
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def ja(n):
    """A synthetic Japanese key (unique per n)."""
    return "こんにちは%03d" % n


def make_work(work, keys, kinds=None, ctx=None, tone=None, bom=False):
    """Build the standard translation work package the tool consumes."""
    work = str(work)
    os.makedirs(work, exist_ok=True)
    write_json(os.path.join(work, "template.json"),
               dict.fromkeys(keys, ""), bom=bom)
    write_json(os.path.join(work, "kinds.json"), kinds or {})
    if ctx is None:
        ctx = {k: {"where": WHERE, "window": [k]} for k in keys}
    write_json(os.path.join(work, "context.json"), ctx)
    if tone is not None:
        with open(os.path.join(work, "tone.md"), "w", encoding="utf-8") as f:
            f.write(tone)
    return work


def run(monkeypatch, work, *extra):
    argv = ["gen_completion_shards.py", str(work)] + [str(x) for x in extra]
    monkeypatch.setattr("sys.argv", argv)
    gcs.main()


def chunk_path(work, n, ext):
    return os.path.join(str(work), "chunks", "chunk_%02d.%s" % (n, ext))


def chunk_keys(work, n):
    return plain_io.load_lines(chunk_path(work, n, "ja.txt"))


def chunk_count(work):
    """How many chunks the run produced (chunk_NN.ja.txt files)."""
    chunks_dir = os.path.join(str(work), "chunks")
    n = 0
    while os.path.exists(os.path.join(chunks_dir, "chunk_%02d.ja.txt" % (n + 1))):
        n += 1
    return n


def read(work, n, ext):
    with open(chunk_path(work, n, ext), encoding="utf-8") as f:
        return f.read()


def all_chunk_keys(work):
    keys = []
    for n in range(1, chunk_count(work) + 1):
        keys += chunk_keys(work, n)
    return keys


class TestChunkArtifacts:
    def test_writes_the_three_chunk_files(self, tmp_path, monkeypatch, capsys):
        keys = [ja(i) for i in range(5)]
        work = make_work(tmp_path / "w", keys)
        run(monkeypatch, work)
        for ext in ("ja.txt", "context.md", "meta.json"):
            assert os.path.exists(chunk_path(work, 1, ext)), ext
        assert chunk_count(work) == 1

    def test_ja_physical_line_count_is_the_agent_contract(self, tmp_path,
                                                          monkeypatch):
        """One physical line per key: that count is what zh.txt must match."""
        keys = [ja(i) for i in range(7)]
        work = make_work(tmp_path / "w", keys)
        run(monkeypatch, work)
        with open(chunk_path(work, 1, "ja.txt"), encoding="utf-8") as f:
            raw = f.read()
        assert raw.count("\n") == len(keys)
        assert raw.endswith("\n")
        assert len(chunk_keys(work, 1)) == len(keys)

    def test_context_declares_the_same_key_count(self, tmp_path, monkeypatch):
        keys = [ja(i) for i in range(4)]
        work = make_work(tmp_path / "w", keys)
        run(monkeypatch, work)
        text = read(work, 1, "context.md")
        assert "chunk_NN.ja.txt: 4 keys (one per line)." in text
        assert "exactly 4 lines, 1:1 in the same order." in text

    def test_control_codes_and_newlines_round_trip(self, tmp_path, monkeypatch):
        keys = ["\\C[27]" + ja(1), ja(2) + "\n" + ja(3), ja(4) + "\\X[2]"]
        work = make_work(tmp_path / "w", keys)
        run(monkeypatch, work)
        assert chunk_keys(work, 1) == keys
        with open(chunk_path(work, 1, "ja.txt"), encoding="utf-8") as f:
            raw = f.read()
        # literal escapes, exactly one key per physical line
        assert "\\\\C[27]" in raw
        assert "\\n" in raw
        assert raw.count("\n") == len(keys)

    def test_agent_zh_file_survives_a_rerun(self, tmp_path, monkeypatch):
        keys = [ja(i) for i in range(3)]
        work = make_work(tmp_path / "w", keys)
        zh = chunk_path(work, 1, "zh.txt")
        os.makedirs(os.path.dirname(zh), exist_ok=True)
        plain_io.save_lines(zh, ["T1", "T2", "T3"])
        run(monkeypatch, work)
        assert plain_io.load_lines(zh) == ["T1", "T2", "T3"]
        assert len(chunk_keys(work, 1)) == 3

    def test_meta_json_lists_the_maps_of_the_chunk(self, tmp_path, monkeypatch):
        """`where` is the human-readable location from build_translation.py
        ("<map name> / EV001 Intro" for map events, a plain file name for DB
        keys, "" when there is none): the label is what precedes the first
        "/" and duplicates collapse to one entry."""
        keys = ["A1", "A2", "A3", "A4", "B1"]
        ctx = {k: {"where": w, "window": [k]} for k, w in (
            ("A1", WHERE), ("A2", "Commons / EV012 Shop"),
            ("A3", WHERE),                  # same map again -> one entry
            ("A4", "/no-map-name"),        # unusable location -> skipped
            ("B1", "Actors.json"))}         # DB file has no "/" -> itself
        work = make_work(tmp_path / "w", keys, ctx=ctx)
        run(monkeypatch, work)
        with open(chunk_path(work, 1, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        assert meta["maps"] == [WHERE, "Commons", "Actors.json"]

    def test_stdout_summarizes_every_chunk(self, tmp_path, monkeypatch, capsys):
        keys = [ja(i) for i in range(3)]
        work = make_work(tmp_path / "w", keys)
        run(monkeypatch, work)
        out = capsys.readouterr().out
        assert "chunks: 1" in out
        assert "chunk_01: 3 keys, %d chars, maps=%s" % (
            sum(len(k) for k in keys), [WHERE]) in out


class TestChunking:
    def test_splits_inside_the_char_budget(self, tmp_path, monkeypatch):
        keys = [ja(i) for i in range(6)]          # 8 chars each
        work = make_work(tmp_path / "w", keys)
        run(monkeypatch, work, "--max-chars", 16)
        assert chunk_count(work) == 3
        for n in range(1, 4):
            assert sum(len(k) for k in chunk_keys(work, n)) <= 16

    def test_no_chunk_may_be_extended(self, tmp_path, monkeypatch):
        """Greedy packing invariant: a non-final chunk cannot take the first
        key of the next chunk without exceeding the cap."""
        keys = [ja(i) for i in range(7)]
        work = make_work(tmp_path / "w", keys)
        budget = 30
        run(monkeypatch, work, "--max-chars", budget)
        assert chunk_count(work) >= 2
        for n in range(1, chunk_count(work)):
            size = sum(len(k) for k in chunk_keys(work, n))
            nxt = chunk_keys(work, n + 1)[0]
            assert size + len(nxt) > budget, n

    def test_keys_are_partitioned_in_story_order(self, tmp_path, monkeypatch):
        keys = [ja(i) for i in range(9)]
        work = make_work(tmp_path / "w", keys)
        run(monkeypatch, work, "--max-chars", 24)
        assert chunk_count(work) == 3
        assert all_chunk_keys(work) == keys     # no loss, no duplicate, order kept

    def test_single_key_longer_than_the_cap_is_not_dropped(self, tmp_path,
                                                           monkeypatch):
        long_key = ja(0) * 5
        keys = [long_key, ja(1)]
        work = make_work(tmp_path / "w", keys)
        run(monkeypatch, work, "--max-chars", 4)
        assert all_chunk_keys(work) == keys

    def test_one_key_template_makes_one_chunk(self, tmp_path, monkeypatch,
                                              capsys):
        work = make_work(tmp_path / "w", [ja(1)])
        run(monkeypatch, work)
        assert chunk_count(work) == 1
        assert chunk_keys(work, 1) == [ja(1)]
        assert "chunk_01: 1 keys" in capsys.readouterr().out

    def test_empty_template_produces_no_chunks(self, tmp_path, monkeypatch,
                                               capsys):
        work = make_work(tmp_path / "w", [])
        run(monkeypatch, work)
        assert chunk_count(work) == 0
        assert "chunks: 0" in capsys.readouterr().out
        chunks_dir = os.path.join(str(work), "chunks")
        assert os.path.isdir(chunks_dir)
        assert list(os.listdir(chunks_dir)) == []
        assert plain_io.load_json(os.path.join(str(work), "glossary.json")) == {}

    def test_bom_written_work_package_is_accepted(self, tmp_path, monkeypatch):
        """build_translation writes the package with a UTF-8 BOM."""
        keys = [ja(i) for i in range(2)]
        work = make_work(tmp_path / "w", keys, bom=True)
        run(monkeypatch, work)
        assert all_chunk_keys(work) == keys


class TestTone:
    def test_missing_tone_falls_back_to_neutral(self, tmp_path, monkeypatch):
        keys = [ja(1)]
        work = make_work(tmp_path / "w", keys)      # no tone.md
        run(monkeypatch, work)
        text = read(work, 1, "context.md")
        assert NEUTRAL_MARKER in text
        assert gts.NEUTRAL_TONE.strip() in text

    def test_work_tone_md_is_used(self, tmp_path, monkeypatch):
        work = make_work(tmp_path / "w", [ja(1)], tone=CUSTOM_TONE + "\n")
        run(monkeypatch, work)
        text = read(work, 1, "context.md")
        assert CUSTOM_TONE in text
        assert NEUTRAL_MARKER not in text

    def test_empty_tone_md_falls_back_to_neutral(self, tmp_path, monkeypatch):
        work = make_work(tmp_path / "w", [ja(1)], tone="  \n\n")
        run(monkeypatch, work)
        text = read(work, 1, "context.md")
        assert NEUTRAL_MARKER in text

    def test_explicit_tone_file_overrides_the_work_package(self, tmp_path,
                                                           monkeypatch):
        work = make_work(tmp_path / "w", [ja(1)], tone="from the package")
        tone_file = tmp_path / "tone.md"
        with open(tone_file, "w", encoding="utf-8-sig") as f:
            f.write(CUSTOM_TONE + "\n")
        run(monkeypatch, work, "--tone", tone_file)
        text = read(work, 1, "context.md")
        assert CUSTOM_TONE in text
        assert "from the package" not in text
        assert "\ufeff" not in text


class TestGlossary:
    def make_dict(self, tmp_path, extra=None):
        d = {
            "Hero": "Hero-san",
            "アリス": "Alice",
            "ユウシャ": "Brave",
            "ab": "Xy",                 # key too short (2 chars)
            "Missing": "Nowhere",       # not in the template
            "Same": "Same",             # identity value
            "Hero!": "Bang",            # not a name-ish key (punctuation)
            "Long": "x",                # value too short
            "ナマエ": "",                # empty value
            "a" * 15: "TooLongKey",     # key too long
        }
        d.update(extra or {})
        path = tmp_path / "mtool.json"
        write_json(path, d)
        return str(path)

    def template_keys(self):
        return ["Hero", "アリス", "ユウシャ", "ab", "Same", "ナマエ", "Long",
                "a" * 15]

    def test_only_usable_matching_entries_become_the_glossary(self, tmp_path,
                                                              monkeypatch,
                                                              capsys):
        work = make_work(tmp_path / "w", self.template_keys())
        run(monkeypatch, work, "--dict", self.make_dict(tmp_path))
        glossary = plain_io.load_json(os.path.join(str(work), "glossary.json"))
        assert glossary == {"Hero": "Hero-san", "アリス": "Alice",
                            "ユウシャ": "Brave"}
        assert "glossary entries: 3" in capsys.readouterr().out

    def test_terms_are_injected_into_the_chunk_that_has_the_key(self, tmp_path,
                                                                monkeypatch):
        keys = ["Hero", "アリス", "ユウシャ", "Same", "ab", "ナマエ", "Long"]
        work = make_work(tmp_path / "w", keys)
        run(monkeypatch, work, "--dict", self.make_dict(tmp_path),
            "--max-chars", 7)           # chunk 1 = Hero+アリス, chunk 2 = ユウシャ
        first = read(work, 1, "context.md")
        second = read(work, 2, "context.md")
        assert "Hero-san" in first
        assert "Alice" in first
        assert "Brave" not in first
        assert "Brave" in second
        assert "Hero-san" not in second

    def test_no_dict_leaves_the_glossary_empty(self, tmp_path, monkeypatch,
                                               capsys):
        work = make_work(tmp_path / "w", ["Hero"])
        run(monkeypatch, work)
        assert plain_io.load_json(os.path.join(str(work), "glossary.json")) == {}
        assert "glossary entries: 0" in capsys.readouterr().out

    def test_missing_dict_file_warns_but_completes(self, tmp_path, monkeypatch,
                                                  caplog, capsys):
        work = make_work(tmp_path / "w", [ja(1)])
        missing = str(tmp_path / "nope.json")
        with caplog.at_level("WARNING", logger="gen_completion_shards"):
            run(monkeypatch, work, "--dict", missing)
        assert any("translation dict not found" in r.getMessage()
                   for r in caplog.records)
        assert chunk_count(work) == 1
        assert plain_io.load_json(os.path.join(str(work), "glossary.json")) == {}


class TestCarryOver:
    def test_first_chunk_has_no_carry_over(self, tmp_path, monkeypatch):
        work = make_work(tmp_path / "w", [ja(i) for i in range(3)])
        run(monkeypatch, work)
        assert "## Carry-over" not in read(work, 1, "context.md")

    def test_second_chunk_carries_the_previous_tail(self, tmp_path, monkeypatch):
        keys = [ja(i) for i in range(6)]
        kinds = dict.fromkeys(keys, "block-line")
        work = make_work(tmp_path / "w", keys, kinds=kinds)
        run(monkeypatch, work, "--max-chars", 24)     # 3 keys per chunk
        section = read(work, 2, "context.md").split("## Carry-over")[1]
        section = section.split("##")[0]
        carried = [ln for ln in section.splitlines() if ln.startswith("- ")]
        assert carried == [f"- {k}" for k in keys[:3]]

    def test_carry_over_is_capped_at_eight_lines(self, tmp_path, monkeypatch):
        keys = ["k%02d" % i for i in range(20)]
        kinds = dict.fromkeys(keys, "event-text")
        ctx = {k: {"where": WHERE, "window": [k]} for k in keys}
        work = make_work(tmp_path / "w", keys, kinds=kinds, ctx=ctx)
        run(monkeypatch, work, "--max-chars", 30)     # 10 keys per chunk
        section = read(work, 2, "context.md").split("## Carry-over")[1]
        section = section.split("##")[0]
        carried = [ln for ln in section.splitlines() if ln.startswith("- ")]
        assert carried == ["- k%02d" % i for i in range(2, 10)]

    def test_non_dialogue_kinds_do_not_carry(self, tmp_path, monkeypatch):
        keys = ["k%02d" % i for i in range(4)]
        kinds = dict.fromkeys(keys, "db-name")          # no dialogue kinds
        work = make_work(tmp_path / "w", keys, kinds=kinds)
        run(monkeypatch, work, "--max-chars", 3)      # 1 key per chunk
        assert chunk_count(work) == 4
        for n in (2, 3, 4):
            assert "## Carry-over" not in read(work, n, "context.md")


class TestSceneTranscript:
    def test_key_and_its_location_are_printed(self, tmp_path, monkeypatch):
        k = ja(1)
        work = make_work(tmp_path / "w", [k],
                         ctx={k: {"where": "Map002.json#ev3#pg0#c0",
                                  "window": [k]}})
        run(monkeypatch, work)
        assert f"[K] {k}   <= Map002.json#ev3#pg0#c0" in read(work, 1,
                                                               "context.md")

    def test_window_flag_limits_the_context_lines(self, tmp_path, monkeypatch):
        k, a, b, c, d = "KEY", "CTX-A", "CTX-B", "CTX-C", "CTX-D"
        ctx = {k: {"where": WHERE, "window": [k, a, b, c, d]}}
        work = make_work(tmp_path / "w", [k], ctx=ctx)
        run(monkeypatch, work, "--window", 1)
        text = read(work, 1, "context.md")
        assert f"  | {a}" in text
        assert f"  | {b}" in text
        assert f"  | {c}" not in text
        assert f"  | {d}" not in text

    def test_context_lines_are_truncated(self, tmp_path, monkeypatch):
        k, long_line = "KEY", "x" * 60
        ctx = {k: {"where": WHERE, "window": [k, long_line]}}
        work = make_work(tmp_path / "w", [k], ctx=ctx)
        run(monkeypatch, work, "--truncate", 10)
        text = read(work, 1, "context.md")
        assert "  | %s" % ("x" * 10) in text
        assert "x" * 11 not in text

    def test_missing_context_is_tolerated(self, tmp_path, monkeypatch):
        keys = [ja(1), ja(2)]
        work = make_work(tmp_path / "w", keys, ctx={})
        run(monkeypatch, work)
        text = read(work, 1, "context.md")
        assert f"[K] {keys[0]}   <= " in text
        with open(chunk_path(work, 1, "meta.json"), encoding="utf-8") as f:
            assert json.load(f)["maps"] == []


class TestBatchAppendContract:
    def test_context_keeps_the_mandatory_rules(self, tmp_path, monkeypatch):
        work = make_work(tmp_path / "w", [ja(1)])
        run(monkeypatch, work)
        text = read(work, 1, "context.md")
        assert "## Rules (batch-append contract, mandatory)" in text
        assert "chunk_NN.zh.txt" in text

    def test_chunk_header_reports_the_key_count(self, tmp_path, monkeypatch):
        keys = [ja(i) for i in range(3)]
        work = make_work(tmp_path / "w", keys)
        run(monkeypatch, work)
        assert "# Chunk 01 - 3 keys" in read(work, 1, "context.md")


@pytest.mark.parametrize("n_keys", [1, 2, 5])
def test_every_chunk_is_self_consistent(tmp_path, monkeypatch, n_keys):
    """Cross-check per chunk: ja.txt lines == header count == the count the
    context file promises the agent, for every chunk size."""
    keys = [ja(i) for i in range(n_keys)]
    work = make_work(tmp_path / "w", keys)
    run(monkeypatch, work)
    assert all_chunk_keys(work) == keys
    for n in range(1, chunk_count(work) + 1):
        count = len(chunk_keys(work, n))
        text = read(work, n, "context.md")
        assert "# Chunk %02d - %d keys" % (n, count) in text
        assert "chunk_NN.ja.txt: %d keys" % count in text
