"""KAG3 tag knowledge: which tags exist, what each means, what was stubbed.

Pass 0 of the conversion (`docs/kirikiri-tyrano.md` §6.1): the tables that
answer "does TyranoScript implement this KAG3 tag, do we shim it, or was it
dropped?" plus the inventory helpers that answer it from the real corpus --
`engine_tag_names()` reads the engine's own registrations, `collect_scene_tags()`
and `collect_tag_usage()` read the game's scripts.

Data plus read-only scanning only (no writes, no other kag module), so tests
and probes can import it cheaply.
"""
import logging
import os
import re

from kirikiri.ks_extract import detect_encoding

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# KAG3-only tags that TyranoScript V6 does not implement.
# Registered as no-op plugin tags so scenarios do not hit undefined_tag.
# ---------------------------------------------------------------------------

# Tags dropped at conversion time. The game's own system-button row lives in
# name.ks/define2.ks as [button graphic=...] (70 sites, no [endbutton]); the
# owner judged the row unnecessary, it overlaps the message text, and its
# buttons need kag.* methods Tyrano does not have. Tyrano's own control bar
# still provides save/load/config/skip. Set from main(); tests may set it too.
_DROPPED_TAGS = set()


SHIM_TAG_NAMES = list(dict.fromkeys([
    "laycount", "startanchor",
    "disablestore", "loadplugin", "style", "resetstyle", "hr", "wm",
    "hact", "endhact", "select_clear", "link2", "pimage",
    "clickskip", "tempsave", "tempload", "locksnapshot", "unlocksnapshot",
    "mes_return", "stoptrans", "mpeg_load", "mpeg_disp", "mpeg_effect",
    "start_mpeg", "stop_mpeg", "videolayer", "preparevideo", "openvideo",
    "playvideo", "stopvideo", "clearvideolayer", "pv_start", "pv_end",
    "staff_roll_wait", "slide_wait", "mapdisablie", "seen_list", "rvo_s",
    "vo_s", "vo_cof", "se_cof", "bgm_cof", "bgm_s", "se_stop", "se_l",
    "fadeoutse", "h_bmp", "faid_in", "faid_out", "faid_in_t", "faid_out_t",
    "t_fadein", "t_fadeout", "t_bmp", "t_off", "t_move", "t_move2",
    "t_mov_init", "t_pos_init", "t_pos_chg", "t_pos_tai", "t_pos_ret",
    "t_alpha_set", "t_sepia_set", "t_flipud_set", "t_ripple_in",
    "t_ripple_out", "m_quake", "wq", "ws", "wv", "flash", "rnd_tr",
    "tr", "bgm_fs", "bgm_fs_w", "bgm_fi", "bgm_l_s", "bgmopt", "fadeinbgm",
    "mask_chips", "cgroom_bmp", "tips_off", "tips_on", "mes_tips_on",
    "name_tips_on", "name_tips_off", "mes_size", "mes_wide", "mes_tips_off",
    "tips_w_on", "c_mark", "c_mark_off", "c_mark_ga", "anime_disp",
    "anime_bot", "anime_auto", "anime_manu", "anime_off", "anime_mode_on",
    "anime_mode_off", "start_anime", "start_anime_nowait", "stop_anime",
    "stop_anime_nowait", "zoomrot", "wzoomrot", "zoom_on", "zoom_off",
    "evcg_a", "evcg_b", "evcg_cng", "evcg_cng_off", "siru_on", "siru_off",
    "skip_bot", "skip_bot_off", "config_bot", "config_bot_off",
    "history_bot", "history_bot_off", "save_bot", "save_bot_off",
    "load_bot", "load_bot_off", "q_save_bot", "q_save_bot_off",
    "q_load_bot", "q_load_bot_off", "voice_bot", "voice_bot_off",
    "menu_bot", "menu_bot_off", "sysmenu", "name_w", "name_m", "name_m2",
    "t_next", "l_next", "rvo", "vo", "b", "b2", "bg", "select_center",
    "select_normal", "select_time_center", "select_a_time_center",
    "select_wide", "select_w_clear", "all_fadein", "all_fadeout",
    "all_tr_in", "all_tr_out", "faid_in_fs", "tr_fs", "flash_fs",
    "t_bmp_fs", "t_fadein_fs", "move_in_fs", "t_ripple_in_fs",
    "m_fadein", "m_fadeout", "m_tr_in", "m_tr_out", "m_mos_in",
    "m_mos_out", "m_turn_in", "m_turn_out", "m_wave_in", "m_wave_out",
    "scroll_u2d", "scroll_d2u", "scroll_l2r", "scroll_r2l", "m_quake_in",
    "t_sepia", "t_ripple", "wv", "wb", "wa", "stoptrans", "mpeg",
    "movie_seen", "movie_seen2", "mpglist", "seen_list", "seen_ani_list",
    "kag", "mes", "pageturn", "noise", "static", "alpha", "graphic",
    "screen", "clickanime", "click_anime", "enter", "leave", "select",
    "start", "end", "load", "save", "menu", "close", "yes", "no",
    "ex", "ex_tips", "ex_menu", "ex_anime", "ex_voice", "ex_config",
    "ex_gallery", "ex_seen", "ex_mpg", "ex_line", "ex_clear", "ex_erase",
    "kag_in", "kag_out", "sys", "sys2", "sys_menu", "system",
    "history", "move", "video", "waittrig", "locklink", "t_init",
    "belt_init", "effect_init", "effect_on", "resetwait", "ruby",
    "cg_image_button", "replay_image_button", "start_anime",
    "movie_seen", "movie_seen2", "seen", "seen2", "save", "load",
    "menu", "close", "yes", "no", "select", "start", "end", "enter",
    "leave", "graphic", "alpha", "noise", "static", "screen",
]))


# System-level scenario files whose iscript bodies are not needed for the
# main story: load/save tests, staff roll, slide galleries. Their iscript
# blocks are commented out (degraded) rather than converted. Feature
# scenarios (gallery/seen/config/submenu) keep their iscript - they are
# plain data or simple TJS and are required for the menus to work.
SYSTEM_ISCRIPT_DROP = {
    "load_test.ks", "loadgame.ks", "save_test.ks", "slide.ks",
    "staff_roll.ks", "config_test.ks", "config_test2.ks", "config_test3.ks",
    "menu_help.ks", "s_select.ks",
    "loadgame.ks", "sys_voice_set.ks", "sys_voice_mload.ks",
    "sys_voice_load.ks", "sys_voice_save.ks", "sys_voice_slide.ks",
    "sys_voice_menu.ks", "sys_voice_mcon.ks", "sys_voice_mpg.ks",
    "sys_voice_seen.ks", "sys_voice_seen_ani.ks", "sys_voice_seen_ani_set.ks",
    "sys_voice_seen_set.ks", "sys_voice_ti.ks", "sys_voice_lmain.ks",
    "zoomrot.ks",
}


# Extra KAG3 tags mapped to a Tyrano equivalent (tag -> replacement attrs).
TAG_MAP = {
    # wm (message window show) -> show message layer
    "wm": "layopt layer=message0 visible=true",
    # bg in KAG3 == background switch; Tyrano has [bg] already, keep name
}


def _strip_js_comments(text):
    """Remove JS comments so a scan cannot mistake commented-out code for a real
    registration.

    This engine keeps several tags as COMMENTED-OUT definitions, e.g.
    `//スタイル変更は未サポート` followed by `/* tyrano.plugin.kag.tag["style"] = ... */`.
    Matching those made the shim drop its no-op for `[style]` while the engine
    does not implement it either, so every `[style]` (59 call sites) raised
    "tag style does not exist" -- a Tyrano alert() that BLOCKS the page (the
    reported popup: no sound, nothing advances, browser says unresponsive).
    """
    out = []
    i, n = 0, len(text)
    state = "code"
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if state == "code":
            if two == "//":
                state = "line"
                i += 2
                continue
            if two == "/*":
                state = "block"
                i += 2
                continue
            if c in "\"'":
                quote = c
                out.append(c)
                i += 1
                while i < n:
                    out.append(text[i])
                    if text[i] == "\\":
                        i += 2
                        out.append(text[i - 1] if i - 1 < n else "")
                        continue
                    if text[i] == quote:
                        i += 1
                        break
                    i += 1
                continue
            out.append(c)
            i += 1
        elif state == "line":
            if c == "\n":
                state = "code"
                out.append(c)
            i += 1
        else:  # block
            if two == "*/":
                state = "code"
                i += 2
                continue
            i += 1
    return "".join(out)


def engine_tag_names(engine_dir):
    """Every tag name the TyranoScript engine itself registers.

    The shim must never register a no-op for one of these: a later
    registration wins, so a no-op silently DISABLES a working engine feature.
    Measured on this engine: playse/stopse/seopt/bgmopt/playbgm/stopbgm/
    fadeinbgm/fadeoutse/fadeoutbgm/style/close/ruby/bg/wa/wb/wq were all
    masked this way -- which is why dialogue voice and sound effects were
    silent even though every file was present.

    Scanned from the engine source so the answer is deterministic at
    conversion time; the emitted JS also re-checks at runtime, so a future
    engine version cannot regress into the same silent failure.
    """
    root = os.path.join(engine_dir, "tyrano")
    found = set()
    if not os.path.isdir(root):
        return found
    pats = (
        re.compile(r"tyrano\.plugin\.kag\.tag\[\s*[\"']([a-z0-9_]+)[\"']\s*\]"),
        re.compile(r"tyrano\.plugin\.kag\.tag\.([a-z0-9_]+)\b"),
        re.compile(r"plugin\.kag\.tag\[\s*[\"']([a-z0-9_]+)[\"']\s*\]"),
    )
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".js"):
                continue
            try:
                text = open(os.path.join(dirpath, fn), encoding="utf-8",
                            errors="replace").read()
            except OSError:
                continue
            text = _strip_js_comments(text)
            for pat in pats:
                found.update(m.lower() for m in pat.findall(text))
    return found


def collect_scene_tags(unpacked):
    """Every tag name the scenarios actually use (outside iscript/comments).

    Used to guarantee the build can never hit Tyrano's undefined_tag error: any
    name the corpus uses that neither the engine nor a game macro provides is
    registered as a no-op. That error is shown through alert(), which BLOCKS the
    page -- measured as repeated popups, no sound and "page unresponsive".
    """
    tags = set()
    root = unpacked
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.lower().endswith(".ks"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                raw = open(path, "rb").read()
                text = raw.decode(detect_encoding(raw), errors="replace")
            except OSError:
                continue
            in_script = False
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("[iscript") or s.startswith("@iscript"):
                    in_script = True
                    continue
                if s.startswith("[endscript") or s.startswith("@endscript"):
                    in_script = False
                    continue
                if in_script or s.startswith(";"):
                    continue
                for m in re.finditer(r"\[([a-z_][a-z0-9_]*)", line, re.I):
                    tags.add(m.group(1).lower())
    return tags


# KAG3 video system -> Tyrano [layermode_movie].
#
# KAG3 splits movie playback across a sequence of tags that share state:
#   [video top=.. left=.. width=.. height=.. loop=.. mode="layer"]  geometry
#   [videolayer channel=1 page=fore layer=N]                        target layer
#   [preparevideo]                                                  no-op
#   [openvideo storage=X]                                           the file
#   [wv]                      wait until ready (before play) / until the end
#   [playvideo]                                                     start
#   [stopvideo] / [clearvideolayer]                                 stop
# Tyrano has no equivalent sequence, but [layermode_movie] does the hard part
# (a <video> composited into the layer stack with a blend mode).  So the tags
# accumulate state here and [playvideo] issues one layermode_movie.
#
# [wv] is state-dependent exactly as in KAG3: before play it waits for the
# file to be ready, after play it waits for the video to end.  It never blocks
# forever: if there is no video, or it is already finished, it advances.
VIDEO_TAGS = ("video", "videolayer", "preparevideo", "openvideo",
              "playvideo", "stopvideo", "clearvideolayer", "wv")


# ---------------------------------------------------------------------------
# Intent preservation for stubbed-out KAG3 tags.
#
# The converter leaves many KAG3-only tags as no-ops and drops a few constructs
# outright. That is acceptable as a first pass, but the project must record WHAT
# each one was supposed to do -- otherwise hand-writing the real behaviour later
# is guesswork (owner directive: 将所有意图都保留下来，即便是空函数，也需要
# 标注意图，方便后续撰写一样的逻辑).
# ---------------------------------------------------------------------------

# Curated intent notes, keyed by lowercase tag name. Anything not listed gets a
# note derived from its own call sites, so nothing is silently opaque.
KAG3_TAG_INTENT = {
    "t_bmp": "display a character sprite: choose the left/centre/right layer from "
             "place= and draw bmp_l/bmp_c/bmp_r on it",
    "t_fadein": "fade a character sprite in (same placement rules as t_bmp)",
    "t_fadeout": "fade a character sprite out",
    "t_off": "hide a character (all, or one side) and clear its saved state",
    "t_move": "move a character sprite to a new position",
    "t_move2": "move a character sprite along both axes",
    "t_mov_init": "reset all character sprite positions to their defaults",
    "t_pos_init": "reset the stored character positions",
    "t_pos_chg": "change the stored character positions",
    "t_pos_tai": "swap two characters' positions",
    "t_pos_ret": "restore previously saved character positions",
    "t_alpha_set": "set a character's alpha (transparency)",
    "t_sepia_set": "set a character's sepia (greyscale tint) amount",
    "t_flipud_set": "set a character's vertical flip",
    "t_ripple_in": "character entrance with a ripple effect",
    "t_ripple_out": "character exit with a ripple effect",
    "t_sepia": "apply a sepia tone to the current characters",
    "t_ripple": "apply a ripple (wave) distortion to the characters",
    "m_quake": "screen shake with the given amplitude and duration",
    "m_quake_in": "screen shake entrance",
    "m_fadein": "fade the whole screen in",
    "m_fadeout": "fade the whole screen out",
    "m_tr_in": "screen transition in",
    "m_tr_out": "screen transition out",
    "m_mos_in": "mosaic transition in",
    "m_mos_out": "mosaic transition out",
    "m_turn_in": "page-turn transition in",
    "m_turn_out": "page-turn transition out",
    "m_wave_in": "wave transition in",
    "m_wave_out": "wave transition out",
    "flash": "white/colour flash overlay for the given duration",
    "quake": "screen shake",
    "mask_chips": "draw the masking overlay used by the adult scenes",
    "cgroom_bmp": "draw a CG inside the gallery room",
    "slide_wait": "wait until the current slide/gallery animation finishes",
    "rnd_tr": "pick one of the given transitions at random",
    "tr": "scripted transition (method table lives in Config.tjs)",
    "bgm_fs": "fade the BGM out to silence",
    "bgm_fs_w": "fade the BGM out to silence and wait",
    "bgm_fi": "fade the BGM in",
    "bgm_l_s": "loop a BGM segment",
    "tips_off": "close the tips (hint) window",
    "tips_on": "open the tips (hint) window",
    "tips_w_on": "open the wide tips window",
    "mes_tips_on": "show a message inside the tips window",
    "mes_tips_off": "hide the tips message",
    "name_tips_on": "show the speaker name inside the tips window",
    "name_tips_off": "hide the tips speaker name",
    "mes_size": "switch the message window size (0 = normal, 1 = small/wide)",
    "mes_wide": "switch the message window to its wide layout",
    "anime_disp": "run a scripted animation sequence",
    "anime_bot": "run an animation sequence from the bottom bar",
    "anime_auto": "play the animation in auto mode",
    "anime_manu": "play the animation in manual mode",
    "anime_off": "stop the animation sequence",
    "anime_mode_on": "enable animation mode",
    "anime_mode_off": "disable animation mode",
    "start_anime": "begin the animation sequence",
    "start_anime_nowait": "begin the animation sequence without waiting",
    "stop_anime": "stop the animation sequence",
    "stop_anime_nowait": "stop the animation sequence without waiting",
    "zoomrot": "zoom and rotate the current layer",
    "wzoomrot": "zoom and rotate the current layer, waiting for completion",
    "zoom_on": "enable the zoom/rotate effect",
    "zoom_off": "disable the zoom/rotate effect",
    "evcg_a": "show a differential CG (variation A)",
    "evcg_b": "show a differential CG (variation B)",
    "evcg_cng": "switch the differential CG",
    "evcg_cng_off": "stop switching the differential CG",
    "siru_on": "show the marker/backdrop badge",
    "siru_off": "hide the marker/backdrop badge",
    "skip_bot": "show the skip button",
    "skip_bot_off": "hide the skip button",
    "config_bot": "show the config button",
    "history_bot": "show the history (backlog) button",
    "save_bot": "show the save button",
    "load_bot": "show the load button",
    "q_save_bot": "show the quick-save button",
    "q_load_bot": "show the quick-load button",
    "voice_bot": "show the voice-repeat button",
    "menu_bot": "show the menu button",
    "vo": "play a character voice file (storage=...)",
    "vo_s": "play a voice and stop the one currently playing",
    "vo_cof": "configure voice playback",
    "se_cof": "configure SE playback",
    "bgm_cof": "configure BGM playback",
    "bgm_s": "start a BGM",
    "se_stop": "stop the SE channel",
    "se_l": "loop an SE",
    "h_bmp": "draw a horizontal (banner) image",
    "faid_in": "fade a layer in",
    "faid_out": "fade a layer out",
    "faid_in_t": "fade a layer in over a given time",
    "faid_out_t": "fade a layer out over a given time",
    "faid_in_fs": "fade a layer in (full-screen variant)",
    "tr_fs": "full-screen transition",
    "flash_fs": "full-screen flash",
    "t_bmp_fs": "full-screen sprite draw",
    "t_fadein_fs": "full-screen sprite fade-in",
    "move_in_fs": "full-screen move-in transition",
    "t_ripple_in_fs": "full-screen ripple entrance",
    "scroll_u2d": "scroll the background upwards to downwards",
    "scroll_d2u": "scroll the background downwards to upwards",
    "scroll_l2r": "scroll the background left to right",
    "scroll_r2l": "scroll the background right to left",
    "mpeg_load": "load an MPEG movie for playback",
    "mpeg_disp": "display the loaded MPEG movie",
    "mpeg_effect": "apply an effect to MPEG playback",
    "mpeg": "play an MPEG movie",
    "start_mpeg": "begin MPEG playback",
    "stop_mpeg": "stop MPEG playback",
    "preparevideo": "prepare the video channel",
    "openvideo": "open a video file into the channel",
    "playvideo": "start video playback",
    "stopvideo": "stop video playback",
    "clearvideolayer": "clear the video layer",
    "videolayer": "choose the layer a video renders into",
    "pv_start": "start the promotional video",
    "pv_end": "end the promotional video",
    "movie_seen": "record that a movie has been viewed (gallery unlock)",
    "seen_list": "add entries to the CG/movie seen list",
    "seen_ani_list": "add entries to the animation seen list",
    "movie_seen2": "record a second kind of movie view (gallery unlock)",
    "seen2": "second seen-list variant",
    "seen": "add to the seen list",
    "staff_roll_wait": "wait until the staff roll finishes",
    "mapdisablie": "disable the clickable map region",
    "clickskip": "enable or disable click-to-skip",
    "tempsave": "write a temporary (auto) save",
    "tempload": "load the temporary (auto) save",
    "locksnapshot": "lock the snapshot save slot",
    "unlocksnapshot": "unlock the snapshot save slot",
    "mes_return": "return to the previous message",
    "resetwait": "clear any pending wait",
    "hact": "start a hair/effect animation",
    "endhact": "end a hair/effect animation",
    "link2": "a second kind of choice link",
    "pimage": "print an image into the message layer",
    "select_clear": "clear the current choice list",
    "startanchor": "define an anchor position",
    "disablestore": "disable saving",
    "loadplugin": "load a KAG plugin",
    "resetstyle": "reset the message style to defaults",
    "hr": "draw a horizontal rule inside the message layer",
    "wm": "show the message window",
    "stoptrans": "stop a running transition",
    "wv": "wait for the video channel to finish",
    "ws": "wait for the SE channel to finish",
    "wq": "wait for the BGM to finish",
    "wa": "wait for all audio channels",
    "wb": "wait for the BGM (alias of wq)",
    "ruby": "draw ruby (furigana) text over the message",
    "laycount": "count/inspect the layers in use",
    "select_normal": "show a standard choice menu",
    "select_center": "show a centred choice menu",
    "select_wide": "show a wide choice menu",
}


def collect_tag_usage(unpacked):
    """Per-tag usage from the corpus: call count, attributes, example sites.

    Drives the intent comments: a stub with neither a recorded intent nor call
    sites cannot be reimplemented later, so nothing stays unannotated.
    """
    usage = {}
    for dirpath, _dirs, files in os.walk(unpacked):
        for fn in files:
            if not fn.lower().endswith(".ks"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                raw = open(path, "rb").read()
                text = raw.decode(detect_encoding(raw), errors="replace")
            except OSError:
                continue
            rel = os.path.relpath(path, unpacked).replace("\\", "/")
            in_script = False
            for lineno, line in enumerate(text.splitlines(), 1):
                s = line.strip()
                if s.startswith("[iscript") or s.startswith("@iscript"):
                    in_script = True
                    continue
                if s.startswith("[endscript") or s.startswith("@endscript"):
                    in_script = False
                    continue
                if in_script or s.startswith(";"):
                    continue
                for m in re.finditer(r"\[([a-z_][a-z0-9_]*)\b([^\]]*)\]", line, re.I):
                    name = m.group(1).lower()
                    rec = usage.setdefault(name, {"count": 0, "attrs": {}, "examples": []})
                    rec["count"] += 1
                    for a in re.findall(r"([a-z_][a-z0-9_]*)\s*=", m.group(2), re.I):
                        rec["attrs"][a.lower()] = rec["attrs"].get(a.lower(), 0) + 1
                    if len(rec["examples"]) < 3:
                        rec["examples"].append("%s:%d: %s" % (
                            rel, lineno, m.group(0)[:110]))
    return usage


def tag_intent(name, usage):
    """One-line statement of what a stubbed tag is supposed to do."""
    note = KAG3_TAG_INTENT.get(name.lower())
    rec = (usage or {}).get(name.lower()) or {}
    if note:
        return note
    attrs = sorted((rec.get("attrs") or {}).keys())
    if attrs:
        return ("unknown KAG3 tag - infer from its call sites; called with: "
                + ", ".join(attrs[:8]))
    return "unknown KAG3 tag with no recorded arguments - inspect its call sites"
