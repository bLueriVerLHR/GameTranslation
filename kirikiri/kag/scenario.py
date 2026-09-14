"""Scenario conversion: `.ks` lines in, TyranoScript lines out (passes 1-2).

Line-level work only -- strip KAG3-only constructs, rewrite `storage=` to the
real file names, translate expressions, balance `[if]/[endif]`, and keep the
line count and line endings of the input (`_finalize_output_lines` holds that
invariant).  Asset lookups go through `assets`, tag tables through `tags`.
"""
import logging
import os
import re

from kirikiri import tjs2js
from kirikiri.kag.assets import _find_asset, _layer_map
from kirikiri.kag.tags import _DROPPED_TAGS, SYSTEM_ISCRIPT_DROP
from kirikiri.ks_extract import detect_encoding

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scenario conversion
# ---------------------------------------------------------------------------

STORAGE_ATTR_RE = re.compile(r'(storage\s*=\s*)(?:"([^"]*)"|\'([^\']*)\'|([^\s>\]]+))')


# KAG3 [button graphic=X] loads its art through the image folder as well, so it
# needs the same treatment as storage= (only `button` uses graphic= in this
# corpus -- measured 70 sites).
GRAPHIC_ATTR_RE = re.compile(r'(graphic\s*=\s*)(?:"([^"]*)"|\'([^\']*)\'|([^\s>\]]+))')


def _wait_to_waitskip(m):
    """Rewrite [wait ...] -> [kagwaitskip time=N] where clickable.

    KAG3 [wait canskip=true time=N] is a timed wait skippable by click, and
    plain [wait time=N] reads as canskip-less in KAG3 but players expect to
    click through dialogue pauses anyway; only explicit canskip=false keeps
    the native hard wait. Dynamic (&f.x) or missing times stay native.
    """
    tag = m.group(0)
    if re.search(r'\bcanskip\s*=\s*"?false"?', tag):
        return tag
    t = re.search(r'\btime\s*=\s*([0-9]+)', tag)
    if t:
        return '[kagwaitskip time=%s]' % t.group(1)
    return tag


def _dangling_call(m, unpacked):
    """Replace a [call]/[jump storage=..] whose target .ks is missing from
    the unpacked tree with an inert [er]; keep it otherwise."""
    storage = m.group(2)
    if not storage.endswith(".ks"):
        return m.group(0)
    base = os.path.join(unpacked, "scenario", storage)
    if os.path.isfile(base):
        return m.group(0)
    if os.path.isfile(os.path.join(unpacked, storage)):
        return m.group(0)
    return "[er]"


def _convert_exp(exp):
    """Minimal TJS2 -> JS expression adjustments.

    Most KAG3 expressions (f./sf./tf. member access, comparisons,
    && / || / !) are already valid JS. Handle the known divergences:
    - TJS `!==`/`===` are already JS.
    - `&&`/`||` are already JS.
    - TJS `++`/`--` work in JS.
    - `kag.` runtime object references are left as-is (may be undefined
      in shim context, guarded by callers).
    """
    return exp


def _strip_comment_tail(line):
    """Drop a KAG3 trailing `;` comment from a line.

    KAG3 treats an unquoted `;` as a comment wherever it appears in a line --
    this game's script writes `[er];`, `[endmacro];` and even a backslash
    followed by `;` for that reason. TyranoScript only ignores `;` at the START of a line, so a
    surviving tail is parsed as message text and printed into the window.

    Only a tail whose preceding text ends with `]` (i.e. it follows a tag) or
    with a stray line-continuation backslash is removed, so a `;` inside an
    attribute value (`exp="{a:1;b:2}"`) or inside dialogue text is never
    touched.
    """
    i, n, quote = 0, len(line), ""
    if line.lstrip().startswith(";"):
        return line
    while i < n:
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == ";":
            before = line[:i].rstrip()
            if before.endswith("\\"):
                before = before[:-1].rstrip()
            if before.endswith("]"):
                return before + line[len(line.rstrip("\r\n")):]
        i += 1
    return line


def _strip_continuation(line, in_script):
    """Remove KAG3 line-continuation backslashes (trailing '\').

    In KAG3 a trailing backslash joins the line to the next one; TyranoScript
    has no such syntax and treats '\' as an escape char, injecting stray
    newlines into the message layer. Inside [iscript] blocks the backslash
    is code and must be kept.
    """
    if in_script:
        return line
    # Some KAG3 scripts join adjacent tags as `]\\[`. Tyrano treats the
    # backslash as an escape and prints the second tag as text, which can also
    # leave [if] blocks structurally open. This separator is unambiguous;
    # ordinary `\\[` text escapes do not follow a closing tag.
    line = re.sub(r"(?<=\])\\(?=\[)", "", line)
    s = line.rstrip("\r\n")
    if s.endswith("\\") and not s.endswith("\\\\"):
        return s[:-1] + line[len(s):]
    return line


def convert_ks_line(line, unpacked, macros, in_script=False):
    """Convert one .ks source line to TyranoScript. Returns new line or None
    to drop the line."""
    line = _strip_continuation(line, in_script)
    s = line.strip()
    if in_script:
        # inside [iscript]: TJS2 -> JS. KAG-plugin classes that cannot be
        # ported (ZoomRot etc. extend KAGPlugin / touch KAG runtime layers)
        # are dropped: their [if exp=...]@iscript guards already keep them
        # out of the critical path, but the TJS syntax would still break
        # the JS eval.
        for drop_marker in ("extends KAGPlugin", "class ZoomRotPlugin"):
            if drop_marker in line:
                return "; // dropped: " + line.strip() + "\n"
        return tjs2js.convert_iscript(line)


    if not s:
        return line
    if s.startswith(";"):
        return line
    if s.startswith("/*"):
        return line
    # labels: *name or *name|chapter (KAG3 also uses *name|chapter)
    if s.startswith("*"):
        return line
    if s.startswith("@"):
        # @tag syntax -> [tag]. The line ending must survive: without it the
        # next source line is glued onto this one (a following `;` comment then
        # ends up mid-line, where Tyrano prints it as dialogue).
        line = "[" + s[1:] + "]" + line[len(line.rstrip("\r\n")):]
    line = _strip_comment_tail(line)
    spans = list(_tag_spans(line))
    if not spans:
        return line
    # Transform each tag in isolation. Rebuilding from tag names alone loses
    # dialogue, and rewriting a whole line applies the first tag's asset rules
    # to unrelated tags (including scenario jumps).
    if len(spans) != 1 or line.strip() != line[spans[0][0]:spans[0][1]]:
        parts = []
        pos = 0
        for start, end in spans:
            parts.append(line[pos:start])
            parts.append(convert_ks_line(line[start:end], unpacked, macros) or "")
            pos = end
        parts.append(line[pos:])
        return "".join(parts)
    s = line.strip()
    # tag line: rewrite storage= attributes to include extensions for
    # ASSET tags only ([image]/[bg]/[playse]/[playbgm]/[movie]/...). KAG3
    # storage="X.ks" on [call]/[jump] must stay untouched (they are scenario
    # files, and asset-name collision would corrupt the jump target).
    first_tag = re.match(r'^\[([a-z0-9_]+)', s, re.I)
    tag_name = first_tag.group(1).lower() if first_tag else ""
    if tag_name in ("image", "bg", "bg2", "playse", "playbgm", "movie",
                    "bgmovie", "graph", "ptext", "chara_show", "chara_mod",
                    "chara_ptext", "button", "glink", "preload",
                    "mapaction", "mapimage"):
        line = STORAGE_ATTR_RE.sub(
            lambda m: m.group(1) + '"' + _find_asset(unpacked, m.group(2) or m.group(3) or m.group(4) or "") + '"',
            line,
        )
        if tag_name in ("button", "glink"):
            # The button art is loaded by the engine through ./data/<folder>/,
            # and Tyrano's own scenario runner calls master_tag[x].start
            # directly (kag.tag.js nextOrder) so a runtime dispatcher hook is
            # not guaranteed to see the tag. Rewriting here is dispatch-proof:
            # _find_asset yields '../bgimage/X.PNG' and $.parseStorage pops the
            # '..' segment, so `[button graphic="history_bot"]` lands on
            # data/bgimage/HISTORY_bot.png instead of data/image/history_bot.
            line = GRAPHIC_ATTR_RE.sub(
                lambda m: m.group(1) + '"' + _find_asset(unpacked, m.group(2) or m.group(3) or m.group(4) or "") + '"',
                line,
            )
    line = re.sub(
        r'(exp|cond)\s*=\s*"([^"]*)"',
        lambda m: '%s="%s"' % (m.group(1), tjs2js.convert_expr(m.group(2))),
        line,
    )
    # KAG3 defaults vs Tyrano vital params: [trans] needs layer (KAG3
    # defaults to base; Tyrano requires it explicitly)
    line = re.sub(
        r'\[trans(?![^\]]*\blayer\s*=)',
        '[trans layer=base',
        line,
    )
    # KAG3 transition methods with no Tyrano/animate.css equivalent
    # (universal/wave/ripple/mosaic) would leave is_trans=true forever:
    # no CSS animation runs, animationend never fires, completeTrans
    # never runs and the following [wt] weak-stop hangs. Map to real
    # animate.css methods (engine-level, applies to any KAG3 game).
    _TRANS_METHODS = {
        "universal": "fadeIn",
        "wave": "fadeIn",
        "ripple": "fadeIn",
        "mosaic": "fadeIn",
        "turn": "flipInX",
        "scroll": "slideInUp",
    }
    line = re.sub(
        r'\[trans\b([^\]]*\bmethod\s*=\s*)(["\']?)([a-zA-Z_0-9]+)\2',
        lambda m: '[trans%s%s%s%s' % (m.group(1), m.group(2),
                                      _TRANS_METHODS.get(m.group(3).lower(), m.group(3)),
                                      m.group(2)),
        line,
    )
    # KAG3 [s] = pure stop (inSleep, no click callback, scenario ends;
    # MainWindow.tjs 's' handler returns -1). The flow is resumed ONLY by
    # window.process()/jump (clickable maps, [link] choices, rclick) or a
    # new scenario load. Tyrano's [l] would let dead-zone clicks advance
    # the flow, so [s] maps to [kag3stop] (see runtime shim).
    line = re.sub(r'^\[s\](\s*)$', lambda m: '[kag3stop]' + m.group(1), line)
    # KAG3 [wait canskip=true time=N] = timed wait skippable by click;
    # Tyrano [wait] hard-blocks clicks for the whole duration -> map to
    # [kagwaitskip] (click-skippable wait defined in the runtime shim).
    # Plain [wait time=N] is also made clickable (players expect to click
    # through dialogue pauses); only explicit canskip=false keeps the
    # native hard wait.
    line = re.sub(
        r'\[wait\b[^\]]*\]',
        _wait_to_waitskip,
        line,
    )
    # dynamic layer references layer=&sf.lay_xxx -> static value from
    # laynumber_init.ks (Tyrano cannot eval them in tag params reliably)
    lm = _layer_map(unpacked)
    if lm:
        line = re.sub(
            r'layer\s*=\s*&sf\.(lay_[a-z0-9_]+)',
            lambda m: 'layer=%s' % lm.get(m.group(1), "base"),
            line,
        )
    # `global` (KAG runtime global) is undefined in Tyrano: neutralize
    # typeof(global.x) guards so they evaluate false instead of throwing
    line = line.replace('typeof(global.', 'typeof(window.')
    line = line.replace('global.', 'window.')
    # dangling [call storage="x.ks"] / [jump storage="x.ks"] where the
    # scenario file does not exist in the source tree: replace with [er]
    # (the original game references missing files; Tyrano would 404)
    line = re.sub(
        r'\[(call|jump)\b[^]]*storage\s*=\s*"([^"]+)"[^]]*\]',
        lambda m: _dangling_call(m, unpacked),
        line,
    )
    line = re.sub(r'^\[s\](\s*)$', lambda m: '[kag3stop]' + m.group(1), line)
    return _remap_part(line)


def _remap_part(part):
    """Convert one top-level tag part: drop disabled tags, then apply the
    layer-replace rewrite."""
    m = re.match(r'^\[([a-z_][a-z0-9_]*)\b', part.lstrip(), re.I)
    if m and m.group(1).lower() in _DROPPED_TAGS:
        # keep the line ending: dropping it glues the next source line on
        return part[len(part.rstrip("\r\n")):]
    return _replace_layer_image(part)


def _replace_layer_image(part):
    """KAG3 `[image layer=N ...]` REPLACES what layer N holds.

    A KAG3 layer holds at most one image per page (fore/back). Tyrano's
    `[image]` tag only ever appends or prepends a new <img> into the layer
    (kag.tag.js), so under a naive name-for-name mapping the layer accumulates
    every image ever drawn on it.

    This game clears a character slot by drawing a transparent placeholder
    (`storage=clear`) over it -- correct under replace semantics, but under
    append semantics the placeholder is stacked ON TOP of the sprite, which
    stays visible underneath. Every character a scene ever loaded therefore
    stays on screen for the rest of the game (measured: one sprite layer
    carried 6 images, and the same character appeared in two layers at once,
    squeezed against the CG that had replaced the scene).

    Fix: emit a layer clear with the SAME layer and page right before the
    image. Tyrano evaluates a leading `&` in any parameter value
    (`convertEntity`), so this game's dynamic layers (`layer=&tf.layer1`) work
    here too. `layer=base` is skipped because the engine's [freeimage] refuses
    the base layer, and the background is replaced properly by [bg].

    Returns the (possibly prefixed) tag text.
    """
    m = re.match(r'^\[(image|graph)\b([^\]]*)\]$', part.strip(), re.I)
    if not m:
        return part
    attrs = m.group(2)
    lm = re.search(r'\blayer\s*=\s*("(?:[^"]*)"|\'(?:[^\']*)\'|[^\s\]]+)', attrs)
    if not lm:
        return part
    layer = lm.group(1).strip('"\'')
    if not layer or layer.lower() == "base":
        return part
    pm = re.search(r'\bpage\s*=\s*("(?:[^"]*)"|\'(?:[^\']*)\'|[^\s\]]+)', attrs)
    page = " page=%s" % pm.group(1) if pm else ""
    # Keep the original line ending: dropping it glues the NEXT source line
    # onto this one, and a following `;` comment then lands in the middle of
    # the tag line, where Tyrano parses it as dialogue text (KAG3 only treats
    # `;` at the start of a line as a comment). That surfaced as comments
    # being printed into the message window.
    tail = part[len(part.rstrip("\r\n")):]
    prefix = "[freeimage layer=%s%s]" % (lm.group(1), page)
    # Tyrano's [image] tag has no opacity parameter, while KAG3 applies it to
    # the image on the layer. Since this pass already enforces KAG3's
    # one-image-per-layer model, setting the layer opacity is equivalent. This
    # is especially important for invisible clickable-map hit surfaces: their
    # solid placeholder bitmap otherwise covers the gallery content.
    om = re.search(r'\bopacity\s*=\s*("(?:[^"]*)"|\'(?:[^\']*)\'|[^\s\]]+)', attrs)
    if om:
        prefix += "[layopt layer=%s%s opacity=%s]" % (lm.group(1), page, om.group(1))
    return "%s%s%s" % (prefix, part.strip(), tail)


def _tag_spans(text):
    """Yield Tyrano-compatible top-level tag spans with source offsets."""
    i, n = 0, len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "[":
            depth, j = 0, i
            quote = ""
            escaped = False
            while j < n:
                char = text[j]
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif quote:
                    if char == quote:
                        quote = ""
                elif char in "\"'`":
                    quote = char
                elif char == "[":
                    depth += 1
                elif char == "]":
                    depth -= 1
                    if depth == 0:
                        yield i, j + 1
                        i = j + 1
                        break
                j += 1
            else:
                break
        else:
            i += 1


def _scan_tags(text):
    """Return the inner text of each complete top-level tag."""
    return [text[start + 1:end - 1] for start, end in _tag_spans(text)]


def _export_globals(js_text):
    """Append window.X = X exports for top-level var/function declarations.

    KAG3 iscript blocks define data containers (anlist, seen_list, ...) as
    top-level `var x = ...`, but TyranoScript executes [iscript] and [eval]
    in separate eval scopes: a `var` in one eval is invisible in the other.
    Re-declaring the top-level names on `window` makes them reachable from
    [eval] expressions (embScript resolves unqualified names through the
    scope chain up to the global object).

    Function declarations need this even more than `var`: `function Foo() {}`
    inside Tyrano's eval() creates a *local* binding in evalScript's scope, so
    a later `[if exp="Foo(x)==1"]` would silently resolve to something else
    (measured: the game's per-character voice check was shadowed by the
    runtime shim's 0-returning fallback stub, which muted every dialogue
    voice).  The declaration regex must therefore accept the two common
    brace styles -- `function f() {` and `function f()\n{` -- because games
    are split roughly evenly between them.
    """
    names = []
    depth = 0
    for line in js_text.splitlines():
        m = re.match(r"^\s*var\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and depth == 0 and m.group(1) not in names:
            names.append(m.group(1))
        # No `\s*\{` at the end: the opening brace may be on the next line
        # (`function f(a)\n{`), which is how this corpus writes it.  A named
        # function declaration is unambiguous without it, and the lines it
        # spans are counted by the depth tracker below, so a nested
        # declaration is still skipped.
        m = re.match(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)", line)
        if m and depth == 0 and m.group(1) not in names:
            names.append(m.group(1))
        depth += line.count("{") - line.count("}")
    if not names:
        return js_text
    export = "\n".join("window.%s = %s;" % (n, n) for n in names)
    return js_text.rstrip("\n") + "\n" + export + "\n"


def _balance_if_endif(lines):
    """Repair if/endif imbalance for TyranoScript's strict deep_if check.

    KAG3 tolerates unbalanced [if]/[endif]: a missing [endif] simply ends
    when the enclosing [macro] block ends, and stray [endif]s are ignored
    by the engine. TyranoScript counts depth per file and errors on any
    mismatch. Strategy:

    - track depth per [macro]...[endmacro] block (macro bodies must be
      self-balanced), skipping [iscript]...[endscript] bodies (their
      content is JS, not tags);
    - an [endif] that would take depth below 0 is replaced by an
      always-true [if] so the file-level depth stays balanced;
    - a macro body that ends with depth > 0 gets matching [endif] lines
      injected just before [endmacro];
    - the file tail gets matching [endif] lines for leftover depth.
    """
    depth = 0
    out = []
    in_script = False
    pending = []

    def inject():
        nonlocal depth
        for _ in range(max(depth, 0)):
            out.append("[endif]\n")
        depth = 0
        pending.clear()

    for ln in lines:
        s = ln.strip()
        if in_script:
            out.append(ln)
            if s.startswith("[endscript") or s.startswith("@endscript"):
                in_script = False
            continue
        if s.startswith("[iscript") or s.startswith("@iscript"):
            in_script = True
            out.append(ln)
            continue
        m_endmacro = re.match(r'^\[endmacro\](\s*)$', s)
        if m_endmacro and depth > 0:
            inject()
        if "[" in s and not s.startswith((";", "*", "/*")):
            tags = [(a, b, s[a + 1:b - 1]) for a, b in _tag_spans(s)]
            rebuilt = ""
            pos = 0
            changed = False
            for (a, b, inner) in tags:
                name = inner.split()[0].lower() if inner.split() else ""
                if name == "endif" and depth <= 0:
                    # stray [endif]: drop it entirely (KAG3 artifact; Tyrano
                    # would underflow its deep_if counter). [er] is a harmless
                    # message-layer clear and leaves if-depth alone.
                    rebuilt += s[pos:a] + "[er]"
                    pos = b
                    changed = True
                    continue
                if name == "if":
                    depth += 1
                elif name == "endif":
                    depth -= 1
                rebuilt += s[pos:b]
                pos = b
            rebuilt += s[pos:]
            out.append(rebuilt if changed else ln)
        else:
            out.append(ln)
        if re.match(r'^\[macro\b', s):
            pending = []
    if depth > 0:
        inject()
    return out


def _finalize_output_lines(lines):
    """Last pass over the converted scenario: one line in, one line out.

    Two invariants, both learned from real defects:

    * no non-script line may end with a KAG3 `;` comment tail -- Tyrano only
      ignores `;` at the start of a line, so a surviving tail is printed as
      message text. Runs after every rewriting pass (the stray-[endif] repair
      rebuilds lines) so nothing can reintroduce one.
    * every entry must carry a line ending. An entry without one glues the next
      entry onto it; that is how original `;` comments ended up inside tag
      lines. [iscript] bodies are JavaScript and skipped.
    """
    out = []
    in_script = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("[iscript") or s.startswith("@iscript"):
            in_script = True
        elif s.startswith("[endscript") or s.startswith("@endscript"):
            in_script = False
        if not in_script:
            ln = _strip_comment_tail(ln)
        if ln and not ln.endswith(("\n", "\r")):
            ln += "\n"
        out.append(ln)
    return out


def convert_scenario_file(src_path, unpacked, out_path, macros, stats):
    # .jsfix override: hand-rewritten JS version produced by a subagent
    # (or manual fix) takes priority over automatic TJS2->JS conversion.
    fix_path = src_path + ".jsfix"
    if os.path.isfile(fix_path):
        with open(fix_path, "r", encoding="utf-8") as f:
            data = f.read()
        # export top-level iscript declarations to window (same as the
        # auto-conversion path) so [eval] can reach them
        data = re.sub(
            r"(\[iscript\])(.*?)(\[endscript\])",
            lambda m: m.group(1) + _export_globals(m.group(2)) + m.group(3),
            data,
            flags=re.S,
        )
        # apply the same line-level tag fixes to the jsfix body
        data = "\n".join(
            re.sub(r'^\[s\](\s*)$', lambda m: '[kag3stop]' + m.group(1), ln)
            for ln in data.splitlines()
        )
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(data)
        stats["files"] += 1
        stats["lines"] += len(data.splitlines())
        stats["jsfix"] += 1
        return "utf-8"
    raw = open(src_path, "rb").read()
    """Convert one .ks file (encoding detect + storage rewrite + UTF-8 out)."""
    raw = open(src_path, "rb").read()
    enc = detect_encoding(raw)
    try:
        text = raw.decode(enc, errors="replace")
    except (UnicodeDecodeError, LookupError):
        text = raw.decode("utf-8", errors="replace")
    out_lines = []
    dropped = 0
    in_script = False
    drop_script = os.path.basename(src_path).lower() in SYSTEM_ISCRIPT_DROP
    script_buf = []
    for ln in text.splitlines(keepends=True):
        s = ln.strip()
        if in_script:
            if s.startswith("[endscript") or s.startswith("@endscript"):
                # end of block: convert the whole block at once (classes
                # and multi-line constructs need the full body)
                if drop_script:
                    out_lines.extend("; // degraded (system iscript): " + b.rstrip("\n") + "\n"
                                      for b in script_buf)
                else:
                    body = tjs2js.convert_iscript("".join(script_buf))
                    # Tyrano's evalScript scope exposes TG (=kag), f/sf/tf/mp
                    # but not `kag`; KAG3 iscript uses kag.* heavily.
                    body = "var kag = TG;\n" + body
                    out_lines.append(_export_globals(body))
                out_lines.append(_strip_continuation(ln, False))
                in_script = False
                script_buf = []
            else:
                script_buf.append(ln)
            continue
        if s.startswith("[iscript") or s.startswith("@iscript"):
            in_script = True
            script_buf = []
            out_lines.append(_strip_continuation(ln, False))
            continue
        nl = convert_ks_line(ln, unpacked, macros, False)
        if nl is None:
            dropped += 1
            continue
        out_lines.append(nl)
    out_lines = _balance_if_endif(out_lines)
    out_lines = _finalize_output_lines(out_lines)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.writelines(out_lines)
    stats["files"] += 1
    stats["lines"] += len(out_lines)
    return enc
