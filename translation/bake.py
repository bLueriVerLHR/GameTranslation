#!/usr/bin/env python3
"""bake.py - write the translated library back into the game (MV / MZ data).

This is the parent's half of the v2 workflow: the translator never touches
JSON, and the *only* place escaping happens is ``rawlib.to_json``; here the
already-escaped, already-gated values are put back where they came from.

Keyed by id, never by line or position: a key's id is its JSON path
(``data/Map003.json#events[2].pages[0].list[7].parameters[0]``), so a bake is
exact and re-runnable - running it twice changes nothing the second time.

Command shapes: MV/MZ accepts both ``[401, 0, "text"]`` (editor arrays) and
``{"code": 401, "indent": 0, "parameters": ["text"]}`` (what a tool that
rewrites data saves).  A path says ``.parameters[N]``, which is index ``N`` of
the ``parameters`` key in the object form and index ``2 + N`` of the array in
the array form; both are handled, because a build ships whichever its last
writer produced.

Fonts: a Chinese translation needs Chinese glyphs.  Per the local font policy
(``docs/reference/local-layout.md``), an MV game is switched by pointing
``fonts/gamefont.css`` at a Simplified-Chinese font that also covers kana -
the game's own ``standardFontFace`` keeps saying ``GameFont``, so no JS change
is needed.  The original font file is never deleted.

Every file this module modifies is backed up into ``<work>/backup/<relpath>``
first, so a bake is always reversible without touching the sources.
"""
import glob
import json
import os
import re
import shutil

__all__ = ["BakeError", "UNIFIED_FONT", "parse_path", "set_by_path",
           "load_plugin_params", "save_plugin_params", "apply_font",
           "apply_font_mz", "unify_plugin_fonts", "bake", "parse_note_id",
           "set_note_payload", "parse_comment_id", "set_comment_payload"]
#: Unified Simplified-Chinese font asset name.  The asset itself is local
#: private data, resolved at run time through the shared mapping (never a path
#: literal in this module - see docs/reference/local-layout.md).
UNIFIED_FONT = "GlowSansSC-Compressed-Regular.otf"
FONT_CSS = os.path.join("fonts", "gamefont.css")


def _font_dir(repo_root=None):
    """Directory of registered font assets (local private data).

    Import is deferred so this module keeps working when it is imported by a
    script that puts `tools/` on `sys.path` without a `rpgmaker` package; the
    resolver is the single place that knows the physical layout.
    """
    from rpgmaker import settings
    return settings.private_path("fonts", repo_root=repo_root)


def _font_decision(policy, font_path, repo_root):
    """Ask the font policy which font this build should use.

    A policy failure that must stop the build is re-raised as ``BakeError`` so
    the CLI reports it like any other refusal instead of a traceback.
    """
    from rpgmaker import fontpolicy

    try:
        return fontpolicy.decide_font(policy, fonts_dir=_font_dir(repo_root),
                                      font_path=font_path)
    except fontpolicy.FontPolicyError as error:
        raise BakeError(str(error)) from error
# --- MZ unified-font strategy (local font policy, see local-layout.md) ------
# MZ loads `fonts/<advanced.mainFontFilename>` as the `rmmz-mainfont` family,
# so an MV-style css rewrite does nothing here.  The standard strategy instead
# declares the faces in `css/game.css` - Han/Latin from the SC font, kana from
# the JP font via `unicode-range` - and clears `mainFontFilename` so the
# engine's own face never wins.  The original font files stay on disk, and
# `numberFontFilename` is left alone (digit-only, still correct).
UNIFIED_FONT_JP = "GlowSansJ-Compressed-Regular.otf"
MZ_CSS = os.path.join("css", "game.css")
MZ_SYSTEM = os.path.join("data", "System.json")
MZ_MARKER = "/* unified-font-policy: MZ unicode-range split (translation bake) */"
#: Families the engine and the unified plugin params ask for.
MZ_FAMILIES = ("rmmz-mainfont", "GameFont")
#: Kana + kana punctuation keep the Japanese face; everything else is Han.
MZ_KANA_RANGE = "U+3040-30FF, U+31F0-31FF, U+30FB-30FC, U+FF66-FF9F"
#: A font-switch plugin re-registers rmmz-mainfont at runtime, so the CSS
#: split would be overwritten - those games get the System.json switch only.
MZ_FONT_SWITCH_PLUGIN = re.compile(
    r"(AnyTimeFontChange|FontChange|FontSwitch|FontLoader|FontChanger)", re.I)

#: A path token is either a name or an `[index]`.  A name may hold any char
#: other than the `.`/`[`/`]` separators: MZ plugin parameters are routinely
#: named in Japanese (`フォント登録リスト`) or contain spaces
#: (`Choice Help Commands`), and restricting names to ASCII identifiers made
#: `bake` raise while rewriting `js/plugins.js` (a real game shipped both).
#: Names only start a path or follow a `.`, so `pages[0]x[0]` stays an error.
_NAME_TOKEN = re.compile(r"[^.\[\]]+")
_INDEX_TOKEN = re.compile(r"\[(\d+)\]")
_PLUGINS_RE = re.compile(r"(\[\s*\{.*\}\s*\])", re.S)


#: A note-payload id: ``<db path>.note#<tag>[<occurrence>]``.  Notes are
#: functional data, so `bake` rewrites the payload of one allowlisted tag -
#: never the note as a whole (see ``mvkeys.note_payloads`` for why a few tag
#: payloads are displayed text).
_NOTE_ID_RE = re.compile(r"^(?P<base>.+\.note)#(?P<tag>[^#\[\]]+)"
                         r"\[(?P<index>\d+)\]$")

#: A comment-payload id: ``<list path>[<head>]#<tag>[<occurrence>]`` - the
#: block form where a plugin reads a menu entry's displayed text out of
#: comment commands (see ``mvkeys.comment_payloads``).
_COMMENT_ID_RE = re.compile(r"^(?P<base>.+\.list)\s*\[(?P<head>\d+)\]#"
                            r"(?P<tag>[^#\[\]]+)\[(?P<index>\d+)\]$")


class BakeError(Exception):
    """A key could not be written back (unknown path, unreadable file)."""


def parse_path(path):
    """``events[2].pages[0].list[7].parameters[0]`` -> tokens.

    Tokens are ``(name, None)`` or ``(None, index)``; the trailing ``[1]`` of a
    choice text (``parameters[0][1]``) is just another index token.  A name may
    hold any character other than the ``.``/``[``/``]`` separators, so
    non-ASCII and spaced parameter names parse too.
    """
    tokens = []
    position = 0
    while position < len(path):
        char = path[position]
        if char == ".":
            position += 1
            match = _NAME_TOKEN.match(path, position)
        elif char == "[":
            match = _INDEX_TOKEN.match(path, position)
        elif not tokens:
            match = _NAME_TOKEN.match(path, position)
        else:
            match = None
        if not match:
            raise BakeError("cannot parse path %r at %d" % (path, position))
        if match.re is _INDEX_TOKEN:
            tokens.append((None, int(match.group(1))))
        else:
            tokens.append((match.group(0), None))
        position = match.end()
    if not tokens:
        raise BakeError("empty path")
    return tokens


def set_by_path(root, tokens, value):
    """Set `value` at `tokens` inside `root`; return True when it was set.

    Handles the array/object command duality: when the current node is a list
    and the token is the name ``parameters``, the realised position is
    ``2 + N`` (the array form stores code, indent, then the parameters).
    """
    node = root
    position = 0
    while position < len(tokens):
        name, index = tokens[position]
        if name == "parameters" and isinstance(node, list) \
                and position + 1 < len(tokens):
            offset = tokens[position + 1][1]
            if offset is None:
                return False
            position += 1                  # consume the "parameters" name
            name, index = None, 2 + offset
        if index is not None:
            if not isinstance(node, list) or index >= len(node):
                return False
            if position == len(tokens) - 1:
                node[index] = value
                return True
            node = node[index]
        else:
            if not isinstance(node, dict) or name not in node:
                return False
            if position == len(tokens) - 1:
                node[name] = value
                return True
            node = node[name]
        position += 1
    return False


def parse_note_id(sub_path):
    """``[12].note#itemCategory[0]`` -> ``('[12].note', 'itemCategory', 0)``."""
    match = _NOTE_ID_RE.match(sub_path)
    if not match:
        raise BakeError(f"cannot parse note path {sub_path!r}")
    return match.group("base"), match.group("tag"), int(match.group("index"))


def parse_comment_id(sub_path):
    """``[1054].list[5]#Subtext Description[0]`` -> list, head, tag, index.

    Returns ``(base, head, tag, occurrence)``: ``base`` addresses the command
    list and ``head`` is the index of the command carrying the opening tag.
    """
    match = _COMMENT_ID_RE.match(sub_path)
    if not match:
        raise BakeError(f"cannot parse comment payload path {sub_path!r}")
    return (match.group("base"), int(match.group("head")),
            match.group("tag"), int(match.group("index")))


def _with_comment_text(command, text):
    """A copy of a comment command with its ``parameters[0]`` replaced."""
    if isinstance(command, dict):
        updated = dict(command)
        params = list(updated.get("parameters") or [])
        params[0] = text
        updated["parameters"] = params
        return updated
    updated = list(command)
    updated[2] = text
    return updated


def set_comment_payload(root, sub_path, text):
    """Rewrite one comment-command payload in place; True when changed.

    Only the payload moves: the opening/closing tag lines, sibling commands and
    every other comment stay byte-identical, because the plugin matches the
    *tag name* - rewriting it would silently drop the menu entry.  A payload
    whose line count no longer matches the source block is refused (the editor
    stores one displayed line per comment command, so a mismatch silently
    drops or duplicates lines).
    """
    from . import mvkeys

    base, head, tag, occurrence = parse_comment_id(sub_path)
    holder = _get_parent(root, parse_path(base))
    if not holder:
        return False
    container, key = holder
    commands = container[key]
    if not isinstance(commands, list):
        return False
    wanted = [p for p in mvkeys.comment_payloads(commands, (tag,))
              if p[0] == tag]
    if occurrence >= len(wanted):
        return False
    opening, lines = wanted[occurrence][3], wanted[occurrence][4]
    if opening != head:
        return False
    command = commands[opening]
    if not mvkeys.is_command(command):
        return False
    text_lines = text.split("\n")
    if lines:
        if len(text_lines) != len(lines):
            return False
        for offset, index in enumerate(lines):
            commands[index] = _with_comment_text(commands[index],
                                                 text_lines[offset])
        return True
    original = mvkeys._comment_text(command)
    if original is None:
        return False
    match = re.search(r"<" + re.escape(tag) + r":(\s*)([^<>]*)>", original)
    if not match:
        return False
    separator = match.group(1) or " "
    commands[opening] = _with_comment_text(
        command, original[:match.start(1)] + separator + text
        + original[match.end(2):])
    return True


def _get_parent(root, tokens):
    """The container and final token ``tokens`` addresses (None when absent).

    Mirrors :func:`set_by_path`'s handling of the array/object command duality
    so a note payload reached through ``parameters[N]`` resolves the same way.
    """
    node = root
    for position, (name, index) in enumerate(tokens):
        last = position == len(tokens) - 1
        if name == "parameters" and isinstance(node, list) and not last:
            offset = tokens[position + 1][1]
            if offset is None:
                return None
            node = node[2 + offset]
            continue
        if index is not None:
            if not isinstance(node, list) or index >= len(node):
                return None
            if last:
                return node, index
            node = node[index]
        else:
            if not isinstance(node, dict) or name not in node:
                return None
            if last:
                return node, name
            node = node[name]
    return None


def set_note_payload(root, sub_path, text):
    """Rewrite one note tag payload in place; True when it was changed.

    Only the payload moves: the tag name (the plugin's lookup key) and every
    other tag in the same note stay byte-identical.  A translation holding
    ``<``/``>`` is refused rather than corrupting the tag syntax.
    """
    if "<" in text or ">" in text:
        return False
    base, tag, occurrence = parse_note_id(sub_path)
    holder = _get_parent(root, parse_path(base))
    if not holder:
        return False
    container, key = holder
    note = container[key]
    if not isinstance(note, str):
        return False
    pattern = re.compile(r"<" + re.escape(tag) + r":([^<>]*)>")
    matches = list(pattern.finditer(note))
    if occurrence >= len(matches):
        return False
    match = matches[occurrence]
    container[key] = note[:match.start(1)] + text + note[match.end(1):]
    return True


def _font_switch_text(game_dir):
    """Raw text search for a font-switch plugin name (fallback only)."""
    path = os.path.join(game_dir, "js", "plugins.js")
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8", errors="replace") as handle:
        return bool(MZ_FONT_SWITCH_PLUGIN.search(handle.read()))


def font_switch_plugin(game_dir):
    """Does an **enabled** plugin re-register the font family at runtime?

    The answer decides which unified-font strategy is legal: such a plugin
    re-registers ``rmmz-mainfont`` from JavaScript, which overrides a CSS
    ``unicode-range`` split, so those builds get the System.json switch only.

    Status is what decides.  A plain text search over the whole file also
    matches *disabled* entries - a real build whose font changer sits at
    ``status: false`` was treated as a font switcher, so the kana face was
    never declared and every script fell back to one Chinese face.  An
    unparseable ``plugins.js`` keeps the conservative answer.
    """
    try:
        plugins, _prefix, _suffix = load_plugin_params(game_dir)
    except BakeError:
        return _font_switch_text(game_dir)
    if not plugins:
        return _font_switch_text(game_dir)
    for plugin in plugins:
        if not isinstance(plugin, dict) or not plugin.get("status"):
            continue
        if MZ_FONT_SWITCH_PLUGIN.search(str(plugin.get("name") or "")):
            return True
    return False


def load_plugin_params(game_dir):
    """``(parameters list, prefix, suffix)`` of ``js/plugins.js``.

    ``plugins.js`` is a JavaScript file holding one JSON array
    (``var $plugins = [...];``); the prefix/suffix are kept so rewriting it
    does not disturb anything else in the file.
    """
    path = os.path.join(game_dir, "js", "plugins.js")
    if not os.path.isfile(path):
        return None, "", ""
    with open(path, encoding="utf-8", errors="replace") as handle:
        source = handle.read()
    match = _PLUGINS_RE.search(source)
    if not match:
        raise BakeError("js/plugins.js does not contain a plugins array")
    try:
        plugins = json.loads(match.group(1))
    except ValueError as error:
        raise BakeError(f"js/plugins.js is not parseable: {error}") from error
    return (plugins, source[:match.start(1)],
            source[match.end(1):])


def save_plugin_params(game_dir, plugins, prefix, suffix):
    """Write ``js/plugins.js`` back (compact JSON, UTF-8, LF, no BOM)."""
    body = json.dumps(plugins, ensure_ascii=False, separators=(",", ":"))
    path = os.path.join(game_dir, "js", "plugins.js")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(prefix + body + suffix)
    return path


def unify_plugin_fonts(game_dir, family="GameFont", backup_dir=None):
    """Point every *font* the game's plugins name at the unified family.

    Found by probing a real build: ``YEP_MessageCore`` ships language-specific
    faces (``Font Name CH = "SimHei, Heiti TC, sans-serif"``) and switches to
    them for Chinese text, so dialogue rendered with a system font while the
    rest of the UI used ``GameFont`` - the game looked like it used two fonts.
    The CSS @font-face alone cannot fix that: the *name* is a plugin parameter.
    Hardcoded ``font-family:`` values in plugin JS (an HUD building its own
    CSS) get the same treatment.  Only font-shaped parameters are touched.

    Returns ``(params_changed, js_files, details)``.
    """
    font_key = re.compile(r"font\s*name|font\s*face|fontname", re.I)
    stack = re.compile(r"^[\w\s,'\"-]+$")
    plugins, prefix, suffix = load_plugin_params(game_dir)
    changed, details = 0, []
    if plugins is not None:
        for plugin in plugins:
            params = plugin.get("parameters") or {}
            for key, value in list(params.items()):
                if not font_key.search(key) or not isinstance(value, str):
                    continue
                if not value.strip() or not stack.match(value):
                    continue
                if family in value and len(value.split(",")) == 1:
                    continue
                details.append("{} / {}: {!r} -> {!r}".format(plugin.get("name"), key, value, family))
                params[key] = family
                changed += 1
        if changed:
            save_plugin_params(game_dir, plugins, prefix, suffix)

    js_files = []
    js_font = re.compile(r"font-family\s*:\s*([^;}]+);")
    for path in sorted(glob.glob(os.path.join(game_dir, "js", "plugins",
                                             "*.js"))):
        with open(path, encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        replaced, count = js_font.subn(f"font-family: {family};", source)
        if not count or replaced == source:
            # Already unified: replacing a value with itself would report a
            # change that did not happen, which makes "is it unified?"
            # unanswerable from the report.
            continue
        _backup_for(game_dir, path, source, backup_dir)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(replaced)
        rel = os.path.relpath(path, game_dir).replace(os.sep, "/")
        js_files.append(rel)
        details.append("%s: %d font-family value(s) -> %s"
                       % (rel, count, family))
    return changed, js_files, details


def _backup_for(game_dir, path, old_text, backup_dir=None):
    """Remember the pre-patch text so the unification stays reversible.

    The sidecar lands in ``<work>/backup`` when a backup dir is given - never
    next to the game file, which would ship a stray ``.prefont`` file in the
    release archive.
    """
    rel = os.path.relpath(path, game_dir).replace(os.sep, "/")
    if backup_dir:
        target = os.path.join(backup_dir, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if not os.path.isfile(target):
            with open(target, "w", encoding="utf-8", newline="\n") as h:
                h.write(old_text)
        return rel
    sidecar = path + ".prefont"
    if not os.path.isfile(sidecar):
        with open(sidecar, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(old_text)
    return rel


def apply_font(game_dir, font_path=None, repo_root=None):
    """Switch the game's font faces to a Simplified-Chinese font.

    Dispatches on the deploy layout: an MV build has `fonts/gamefont.css` (a
    single face to repoint), an MZ build has `data/System.json` (see
    ``apply_font_mz``).  Returns ``(changed_files, warnings)``.  A missing font
    asset is a warning, never a silent skip: shipping a Chinese build with a
    kana-only font means every Chinese character renders as a box.
    """
    if os.path.isfile(os.path.join(game_dir, MZ_SYSTEM)) \
            and not os.path.isfile(os.path.join(game_dir, FONT_CSS)):
        return apply_font_mz(game_dir, font_path=font_path,
                             repo_root=repo_root)
    warnings = []
    css_path = os.path.join(game_dir, FONT_CSS)
    if not os.path.isfile(css_path):
        return [], [f"no {FONT_CSS} (not an MV build?)"]
    font_path = font_path or os.path.join(_font_dir(repo_root), UNIFIED_FONT)
    if not os.path.isfile(font_path):
        return [], [f"unified font asset missing: {font_path}"]
    with open(css_path, encoding="utf-8", errors="replace") as handle:
        css = handle.read()
    if UNIFIED_FONT in css:
        return [], []
    replaced, count = re.subn(r'src:\s*url\((?:"|\')?[^"\')]+(?:"|\')?\)',
                              f'src: url("{UNIFIED_FONT}")', css)
    if not count:
        return [], [f"{FONT_CSS} has no @font-face src to switch"]
    destination = os.path.join(game_dir, "fonts", UNIFIED_FONT)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copyfile(font_path, destination)
    with open(css_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(replaced)
    return [FONT_CSS, os.path.join("fonts", UNIFIED_FONT)], warnings


def apply_font_mz(game_dir, font_path=None, repo_root=None, jp_path=None):
    """MZ unified-font policy: unicode-range split faces in ``css/game.css``.

    Returns ``(changed_files, warnings)``.  A font-switch plugin is honoured by
    switching only ``data/System.json`` (its runtime ``FontFace`` registration
    would override any CSS split) - that is the documented rule in the local
    font policy (``docs/reference/local-layout.md``).
    """
    system_path = os.path.join(game_dir, MZ_SYSTEM)
    if not os.path.isfile(system_path):
        return [], ["no {} (not an MZ build?)".format(MZ_SYSTEM.replace(os.sep, "/"))]
    font_path = font_path or os.path.join(_font_dir(repo_root), UNIFIED_FONT)
    if not os.path.isfile(font_path):
        return [], [f"unified font asset missing: {font_path}"]
    jp_path = jp_path or os.path.join(_font_dir(repo_root), UNIFIED_FONT_JP)
    jp_asset = os.path.isfile(jp_path)

    plugins_path = os.path.join(game_dir, "js", "plugins.js")
    font_plugin = os.path.isfile(plugins_path) and font_switch_plugin(game_dir)

    with open(system_path, encoding="utf-8-sig") as handle:
        system = json.load(handle)
    advanced = system.setdefault("advanced", {})
    warnings = []
    changed = []

    fonts_dir = os.path.join(game_dir, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)

    def install(source, name):
        """Copy the asset in unless it is already there byte-for-byte."""
        destination = os.path.join(fonts_dir, name)
        if os.path.isfile(destination) \
                and os.path.getsize(destination) == os.path.getsize(source):
            return
        shutil.copyfile(source, destination)
        changed.append("fonts/" + name)

    install(font_path, UNIFIED_FONT)
    if jp_asset:
        install(jp_path, UNIFIED_FONT_JP)

    if font_plugin:
        warnings.append(
            "a font-switch plugin is enabled: switching only "
            "data/System.json (its runtime FontFace would override a CSS "
            "split) - see the local font policy in "
            "docs/reference/local-layout.md")
        target = UNIFIED_FONT
    else:
        target = ""
        css_path = os.path.join(game_dir, MZ_CSS)
        if not os.path.isfile(css_path):
            warnings.append("no css/game.css: could not declare the split faces")
        else:
            with open(css_path, encoding="utf-8", errors="replace") as h:
                css = h.read()
            if MZ_MARKER not in css:
                blocks = [MZ_MARKER]
                for family in MZ_FAMILIES:
                    blocks.append(f'@font-face {{\n    font-family: {family};\n'
                                  f'    src: url("../fonts/{UNIFIED_FONT}");\n}}')
                    if jp_asset:
                        blocks.append(f'@font-face {{\n    font-family: {family};\n'
                                      f'    src: url("../fonts/{UNIFIED_FONT_JP}");\n'
                                      f'    unicode-range: {MZ_KANA_RANGE};\n}}')
                with open(css_path, "w", encoding="utf-8",
                             newline="\n") as h:
                    h.write(css.rstrip("\n") + "\n\n" + "\n".join(blocks) + "\n")
                changed.append(MZ_CSS.replace(os.sep, "/"))
            if not jp_asset:
                warnings.append(f"JP fallback font missing: {jp_path} (kana face "
                                "not declared)")

    old_name = advanced.get("mainFontFilename")
    if old_name != target:
        advanced["mainFontFilename"] = target
        with open(system_path, "w", encoding="utf-8", newline="\n") as h:
            h.write(json.dumps(system, ensure_ascii=False, separators=(",", ":")))
        changed.append(MZ_SYSTEM.replace(os.sep, "/"))
    return changed, warnings


def _backup(work_dir, game_dir, rel):
    source = os.path.join(game_dir, rel)
    if not os.path.isfile(source):
        return
    target = os.path.join(work_dir, "backup", rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if not os.path.isfile(target):
        shutil.copyfile(source, target)


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False,
                                separators=(",", ":")))


def _apply_values(game_dir, values, work_dir, dry_run):
    """Write each translated key into its game file; return what changed.

    Returns ``(written, applied, skipped, plugin_edit)`` where `plugin_edit` is
    ``(plugins, prefix, suffix)`` when `js/plugins.js` was touched (its
    parameters are edited in memory and saved once at the end, not per key),
    else None.
    """
    by_file = {}
    for key_id, text in values.items():
        rel, _, path = key_id.partition("#")
        by_file.setdefault(rel, {})[path] = text

    written, applied, skipped = [], 0, []
    plugin_edit = None
    for rel, entries in sorted(by_file.items()):
        if rel == "js/plugins.js":
            plugins, prefix, suffix = load_plugin_params(game_dir)
            plugin_edit = (plugins, prefix, suffix)
            for path, text in entries.items():
                tokens = parse_path(path)
                index = tokens[0][1]
                key = tokens[-1][0]
                if plugins is None or index is None or index >= len(plugins):
                    skipped.append((f"{rel}#{path}", "plugin missing"))
                    continue
                params = plugins[index].get("parameters") or {}
                if key not in params:
                    skipped.append((f"{rel}#{path}", "param missing"))
                    continue
                params[key] = text
                applied += 1
            continue
        path = os.path.join(game_dir, rel)
        if not os.path.isfile(path):
            skipped.append((rel, "file missing"))
            continue
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        changed = False
        for sub_path, text in entries.items():
            try:
                if _COMMENT_ID_RE.match(sub_path):
                    ok = set_comment_payload(payload, sub_path, text)
                elif "#" in sub_path:
                    ok = set_note_payload(payload, sub_path, text)
                else:
                    ok = set_by_path(payload, parse_path(sub_path), text)
            except BakeError as error:
                skipped.append((f"{rel}#{sub_path}", str(error)))
                continue
            if ok:
                applied += 1
                changed = True
            else:
                skipped.append((f"{rel}#{sub_path}", "path not found"))
        if changed:
            if not dry_run:
                _backup(work_dir, game_dir, rel)
                _write_json(path, payload)
            written.append(rel)
    return written, applied, skipped, plugin_edit


def _apply_font(game_dir, work_dir, apply_unified_font, dry_run, font_policy,
                font_path, repo_root):
    """Apply the unified-font policy; return ``(files, warnings, report, details)``.

    Only the ``required`` policy can write anything: ``auto`` is report-only by
    design, so a caller that says nothing cannot have font files rewritten
    under it (see docs/reference/local-layout.md).
    """
    if not apply_unified_font:
        return [], [], {}, []
    if dry_run:
        return [], ["dry run: unified font not installed"], {}, []
    decision = _font_decision(font_policy, font_path, repo_root)
    font_details = [decision.detail]
    warnings = list(decision.warnings)
    if not decision.apply:
        return [], warnings, {"policy": decision.policy,
                              "source": decision.source,
                              "applied": False}, font_details
    font_files, apply_warnings = apply_font(
        game_dir, font_path=decision.path, repo_root=repo_root)
    warnings += apply_warnings
    for rel in font_files:
        if rel != os.path.join("fonts", UNIFIED_FONT):
            _backup(work_dir, game_dir, rel)
    changed, js_files, details = unify_plugin_fonts(
        game_dir, backup_dir=os.path.join(work_dir, "backup"))
    if changed:
        _backup(work_dir, game_dir, "js/plugins.js")
    font_files += js_files
    for rel in js_files:
        _backup(work_dir, game_dir, rel)
    font_details += details
    report = {"params": changed, "files": js_files,
              "policy": decision.policy, "source": decision.source}
    return font_files, warnings, report, font_details


def bake(game_dir, work_dir, apply_unified_font=True, repo_root=None,
         font_path=None, dry_run=False, font_only=False, write_kv=True,
         font_policy="auto"):
    """Write every translated key back into the game; return a report.

    With ``dry_run`` nothing is written and nothing is backed up: the report
    says what *would* change, which is how a build is inspected before touching
    it.

    ``font_policy`` decides whether the project font is applied at all; the
    library default is the report-only ``auto`` so a caller that says nothing
    cannot have files rewritten under it.  A delivery run passes ``required``
    (the CLI default), which fails loudly rather than shipping a build whose
    Chinese text renders as boxes.
    """
    values = {}
    if not font_only:
        ids_path = os.path.join(work_dir, "translated_ids.json")
        if not os.path.isfile(ids_path):
            raise BakeError(f"translated_ids.json missing in {work_dir} (run to-json)")
        with open(ids_path, encoding="utf-8") as handle:
            values = json.load(handle)

    written, applied, skipped, plugin_edit = _apply_values(
        game_dir, values, work_dir, dry_run)
    font_files, warnings, report_font, font_details = _apply_font(
        game_dir, work_dir, apply_unified_font, dry_run, font_policy, font_path,
        repo_root)
    if plugin_edit is not None:
        plugins, prefix, suffix = plugin_edit
        if not dry_run:
            _backup(work_dir, game_dir, "js/plugins.js")
            save_plugin_params(game_dir, plugins, prefix, suffix)
            written.append("js/plugins.js")
        elif not font_only:
            written.append("js/plugins.js (dry run)")

    kv_path = None
    if write_kv and not dry_run and not font_only:
        # House rule: the translation dictionary ships with the game, so the
        # text can be revised later without re-extracting the whole game.
        source = os.path.join(work_dir, "translated.json")
        if os.path.isfile(source):
            kv_path = os.path.join(game_dir, "translation_kv.json")
            shutil.copyfile(source, kv_path)

    return {
        "keys": len(values),
        "applied": applied,
        "skipped": len(skipped),
        "skipped_detail": skipped[:50],
        "files": sorted(set(written)),
        "font_files": font_files,
        "font_warnings": warnings,
        "font_report": report_font,
        "font_details": font_details[:20],
        "translation_kv": kv_path,
        "backup_dir": os.path.join(work_dir, "backup"),
    }
