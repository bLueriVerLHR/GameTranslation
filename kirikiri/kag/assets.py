"""Asset resolution and conversion (pass 3 in docs/kirikiri-tyrano.md §6.1).

KAG3 scripts name assets without an extension and resolve them relative to
tag-specific roots; TyranoScript resolves `storage=` per tag directory.  Here
that becomes explicit: the name -> real-file maps (static at build time, plus
the runtime maps the shim resolves against) and the media conversion itself
(TLG/BMP -> PNG, clickable-map region images, movies -> WebM).

`_decoder_mtime()` is deliberately part of the image cache key -- see its
docstring: a decoder fix must invalidate the images it produced.
"""
import logging
import os
import re
import shutil
from concurrent.futures import (ProcessPoolExecutor, ThreadPoolExecutor,
                                as_completed)

from kirikiri import tlg
from kirikiri.ks_extract import decode_text, detect_encoding
from rpgmaker import platform, runtime
import contextlib

log = logging.getLogger(__name__)


def _asset_map(unpacked):
    """Build {lower_basename: out_relpath} for the whole asset tree.

    out_relpath is the asset's ONE canonical location, including its directory
    (`bgimage/telop1.png`).  It accounts for format conversion (tlg/bmp ->
    png), directory moves (rule -> fgimage) and subdirectories
    (fgimage/select/x -> fgimage/select/x).

    The directory is part of the value because each asset is written exactly
    once: the runtime resolves names to `../<dir>/<file>`, which works from
    any tag's folder because browsers normalise dot segments in URLs
    (measured: `./data/fgimage/../bgimage/x.png` arrives as
    `/data/bgimage/x.png`).  Writing a copy into every directory a tag might
    look in tripled the build and ~75% of that survived compression.

    Image extensions win over same-named non-images (map01_01.bmp + the
    map01_01.ma action file share the basename: the image must win).
    """
    mapping = {
        "bgimage": "bgimage",
        "fgimage": "fgimage",
        "image": "image",
        "bgm": "bgm",
        "sound": "sound",
        "video": "video",
        "rule": "fgimage",
    }
    img_exts = ("png", "jpg", "jpeg", "gif", "bmp", "tlg", "webp")
    amap = {}
    full = {}

    def _scan(src_sub, parts=(), want_img=None):
        d = os.path.join(unpacked, src_sub, *parts)
        if not os.path.isdir(d):
            return
        for fn in sorted(os.listdir(d)):
            sp = os.path.join(d, fn)
            if os.path.isdir(sp):
                _scan(src_sub, parts + (fn,), want_img)
                continue
            base = fn.rsplit(".", 1)[0].lower() if "." in fn else fn.lower()
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if want_img is not None and (ext in img_exts) != want_img:
                continue
            # Storage keys are always slash-separated: they end up inside
            # generated TyranoScript/HTML references, so they must not follow
            # the host OS separator (a Windows build would emit "select\\x.png").
            name = base + ".png" if ext in ("tlg", "bmp") else fn
            out = "/".join((mapping[src_sub],) + tuple(parts) + (name,))
            full.setdefault(base + "." + ext, out)
            amap.setdefault(base, out)

    # two passes: images first so a same-named .ma (map01_01.ma vs the
    # map01_01 image) never shadows the image for extensionless storages
    for src_sub in mapping:
        _scan(src_sub, (), want_img=True)
    for src_sub in mapping:
        _scan(src_sub, (), want_img=False)
    return amap, full


def _asset_map_full(unpacked):
    """{lower_basename_with_ext: out_relpath} for every asset (no preference)."""
    return _asset_map(unpacked)[1]


def _asset_map_from_output(out_data):
    """Index canonical assets already present in a Tyrano ``data`` tree.

    ``--scenario-only`` intentionally keeps the prior converted assets. The
    runtime resolver must include those files even when the reduced source
    tree used for a quick scenario rebuild contains no asset folders. Values
    use the same ``<folder>/<file>`` form returned by ``_asset_map``.
    """
    asset_dirs = ("bgimage", "fgimage", "image", "bgm", "sound", "video")
    img_exts = ("png", "jpg", "jpeg", "gif", "bmp", "webp")
    amap = {}
    full = {}

    def _scan(want_img):
        for asset_dir in asset_dirs:
            root = os.path.join(out_data, asset_dir)
            if not os.path.isdir(root):
                continue
            for dp, _, fns in os.walk(root):
                for fn in sorted(fns):
                    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
                    if (ext in img_exts) != want_img:
                        continue
                    base = fn.rsplit(".", 1)[0].lower() if "." in fn else fn.lower()
                    rel = os.path.relpath(os.path.join(dp, fn), out_data).replace("\\", "/")
                    full.setdefault(base + ("." + ext if ext else ""), rel)
                    amap.setdefault(base, rel)

    _scan(True)
    _scan(False)
    return amap, full


_ASSET_CACHE = {}


# Extensions that mean "this asset-map value is a picture".  Used when two
# trees disagree about a stem (see _merge_asset_maps).
IMAGE_EXTS = ("png", "jpg", "jpeg", "gif", "bmp", "tlg", "webp")


def _is_image_asset(value):
    """True when an asset-map value points at a picture (by extension)."""
    return bool(value) and value.rsplit(".", 1)[-1].lower() in IMAGE_EXTS


def _merge_asset_maps(base, extra):
    """Merge `extra` into `base`, letting an image beat a same-stem non-image.

    KAG3 ships a clickable-map action file (`X.MA`) next to the screen art
    (`X.png`) under one stem, and the art is what `[image storage=X]` means.
    A rebuild that reads a REDUCED source tree sees only the `.MA`, so a plain
    `setdefault` merge pins the stem to the map file even though the build
    still holds the picture.  The runtime then hands an `<img>` a text file,
    the browser cannot decode it and the screen stays BLACK while its click
    regions keep working (measured on a title menu: the menu was invisible but
    still clickable, so an invisible exit region could be hit by accident).

    `extra` wins only where the source tree has no picture under that stem (or
    nothing at all); between two pictures the source tree still decides.

    Returns `base` for convenience.
    """
    for key, value in extra.items():
        current = base.get(key)
        if current is None or (_is_image_asset(value) and not _is_image_asset(current)):
            base[key] = value
    return base


def _runtime_asset_maps(unpacked, out_data, scenario_only=False):
    """The (stem map, extension map) pair the runtime storage resolver uses.

    `scenario_only` rebuilds keep the assets of the previous build, so the
    output tree - not the (possibly reduced) source tree - is the ground truth
    for which files exist; it is merged in with image preference.
    """
    amap, full_map = _asset_map(unpacked)
    if scenario_only:
        retained_amap, retained_full = _asset_map_from_output(out_data)
        _merge_asset_maps(amap, retained_amap)
        _merge_asset_maps(full_map, retained_full)
    return amap, full_map


def _layer_map(unpacked):
    """Parse sf.lay_xxx = N assignments from laynumber_init.ks (layer ids)."""
    lm = {}
    p = os.path.join(unpacked, "scenario", "laynumber_init.ks")
    if not os.path.isfile(p):
        return lm
    raw = open(p, "rb").read()
    # errors="replace": a byte the detected codec rejects must not lose the
    # whole layer table (see kirikiri.ks_extract.decode_text).
    try:
        txt = decode_text(raw, detect_encoding(raw))
    except LookupError:
        # Unreachable from detect_encoding (it only returns known names), kept
        # so an unknown codec name cannot escape as an exception here.
        return lm
    for m in re.finditer(r'sf\.(lay_[a-z0-9_]+)\s*=\s*(\d+)', txt):
        lm[m.group(1)] = m.group(2)
    return lm


def _find_asset(unpacked, name):
    """Resolve a storage= value against the asset tree.

    Handles extensionless names (black -> BLACK.PNG / black.png after
    conversion), names whose source extension changed during conversion
    (telop1.bmp -> telop1.png) and exact names with extension (title.ma ->
    TITLE.MA, preserving on-disk case).

    Returns `../<dir>/<file>`: a path relative to whatever `data/<folder>/`
    the receiving tag will prepend, so it hits the asset's single canonical
    location no matter which tag asks.  The browser normalises the dot
    segment (measured), so even engine code that concatenates the folder by
    hand lands on the right URL.
    """
    if not name or "/" in name or "\\" in name:
        return name
    key = unpacked
    if key not in _ASSET_CACHE:
        _ASSET_CACHE[key] = _asset_map(unpacked)
    amap, full = _ASSET_CACHE[key]
    base = name.lower()
    if base in full:
        return "../" + full[base]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    hit = amap.get(stem)
    return "../" + hit if hit else name


def _is_region_image(fn):
    """True for clickable-map province images (main_name + _p + image ext).

    KAG3 maps use a palette-indexed "province image" next to the main image
    (map_p.png); the palette index of a pixel is the region number.
    """
    lower = fn.lower()
    return lower.endswith(("_p.png", "_p.bmp", "_p.tlg", "_p.jpg"))


def _convert_region_image(src, dst, stats):
    """Rewrite a province image as a grayscale PNG where gray = palette index.

    Browsers render indexed PNGs to RGBA (palette colors), losing the index;
    converting so that pixel gray == palette index lets the runtime read the
    region number straight from the R channel. Non-indexed sources keep their
    R channel (best effort; such images are broken maps anyway).
    """
    _apply_image_result(stats, src, dst, *_image_job(src, dst, "region"))


def _convert_videos(unpacked, out_data, video_dir, stats):
    """Collect movies from anywhere in the unpacked tree into data/video/.

    KAG3 games keep .wmv/.mpg under `others/`, which is not an image dir, so
    a directory-driven copy misses them entirely.  Browsers cannot play WMV,
    so each file is replaced by a WebM produced beforehand by
    `transcode_video.py` (found via `video_dir`, defaulting to
    `<unpacked>/_video_webm`, or next to the source).  A movie with no WebM
    available is copied as-is and WARNed about: it is better to ship a file
    the browser refuses than to silently drop a scene's video.

    Returns {name_lower: "<stem>.webm"} for the runtime resolver, keyed both
    by the original name with and without extension so an extensionless
    `[openvideo storage=X]` lookup works.
    """
    exts = (".wmv", ".mpg", ".mpeg", ".avi")
    found = []
    for dp, dirnames, fns in os.walk(unpacked):
        dirnames[:] = [d for d in dirnames if d not in ("_video_webm",)]
        found.extend(os.path.join(dp, fn) for fn in fns
                     if fn.lower().endswith(exts))
    if not found:
        return {}

    out_dir = os.path.join(out_data, "video")
    os.makedirs(out_dir, exist_ok=True)
    stats.setdefault("video_stale", 0)
    vmap = {}
    for src in sorted(found):
        stem = os.path.splitext(os.path.basename(src))[0]
        webm = None
        for cand in (os.path.join(video_dir, stem + ".webm") if video_dir else None,
                     os.path.join(os.path.dirname(src), stem + ".webm"),
                     os.path.splitext(src)[0] + ".webm"):
            if cand and os.path.isfile(cand):
                webm = cand
                break
        if webm:
            shutil.copy2(webm, os.path.join(out_dir, stem + ".webm"))
            # Self-heal: an earlier run (before the WebM cache existed) may have
            # copied the raw container here as well.  Measured on a real game:
            # a build kept 446 stale .mpg/.wmv next to their 222 .webm
            # counterparts - ~1.3 GiB of files no browser can play.  Only files
            # with this video's own stem are touched.
            for name in os.listdir(out_dir):
                if os.path.splitext(name)[0].lower() != stem.lower():
                    continue
                if os.path.splitext(name)[1].lower() not in exts:
                    continue
                os.remove(os.path.join(out_dir, name))
                stats["video_stale"] += 1
            vmap[stem.lower()] = stem + ".webm"
            vmap[os.path.basename(src).lower()] = stem + ".webm"
            stats["video"] += 1
        else:
            shutil.copy2(src, os.path.join(out_dir, os.path.basename(src)))
            vmap[stem.lower()] = os.path.basename(src)
            vmap[os.path.basename(src).lower()] = os.path.basename(src)
            stats["video_raw"] += 1
            log.warning("video %s has no WebM counterpart (looked in %s) - "
                        "copied as-is; browsers cannot play %s",
                        os.path.relpath(src, unpacked), video_dir or "-",
                        os.path.splitext(src)[1])
    log.info("videos: %d -> %s (+%d raw, %d stale raw removed)",
             stats["video"], out_dir, stats["video_raw"],
             stats.get("video_stale", 0))
    return vmap


def _video_map_from_output(out_data):
    """Rebuild the runtime video resolver from retained converted files."""
    root = os.path.join(out_data, "video")
    if not os.path.isdir(root):
        return {}
    vmap = {}
    for fn in sorted(os.listdir(root)):
        path = os.path.join(root, fn)
        if not os.path.isfile(path):
            continue
        stem = os.path.splitext(fn)[0].lower()
        vmap.setdefault(stem, fn)
        vmap.setdefault(fn.lower(), fn)
    return vmap


#: Source asset folder -> Tyrano ``data/`` folder.  The destination matters:
#: TyranoScript resolves ``storage=`` *per tag directory* (a ``[bg]`` looks under
#: bgimage/, ``[playse]`` under sound/, ...), so an asset placed in the wrong
#: folder is an asset the game cannot find.  These names cover the dialect
#: variants seen in real KAG3 games; anything unknown is kept under its own name
#: (never dropped) and a game can override the table via its profile.
DEFAULT_ASSET_DIRS = {
    "bgimage": "bgimage", "bg": "bgimage", "background": "bgimage",
    "fgimage": "fgimage", "face": "fgimage", "frame": "fgimage",
    "effect": "fgimage", "rule": "fgimage", "emotion": "fgimage",
    "image": "image", "thumb": "image", "thumbnail": "image",
    "credit": "image", "systemimage": "image",
    "bgm": "bgm",
    "sound": "sound", "se": "sound", "voice": "sound", "envse": "sound",
    "video": "video", "movie": "video", "movies": "video",
    "system": "system", "font": "font", "fonts": "font",
}

#: Root-level files (some repacks put every asset next to the scripts) are
#: placed by extension, because the folder is what a Tyrano tag resolves
#: against.  Anything else at the root is engine config/data and is skipped.
ROOT_ASSET_EXTS = {
    "video": (".mpg", ".mpeg", ".wmv", ".avi", ".mp4", ".webm"),
    "sound": (".ogg", ".wav", ".mp3", ".m4a", ".opus", ".sli"),
    "image": (".tlg", ".bmp", ".png", ".jpg", ".jpeg", ".gif", ".webp"),
}

#: Raw video containers no browser/WebView can play: copying them into a build
#: only bloats the package (measured: one game carries ~200 MiB of .wmv the
#: engine cannot display; another 223 .mpg + 223 .wmv = most of its 1.8 GiB).
#: Playable containers (.mp4/.webm, and whatever --video-dir transcoded) are
#: still copied, and the drop is reported so a port never loses video silently.
UNPLAYABLE_VIDEO_EXTS = (".wmv", ".mpg", ".mpeg", ".avi", ".rm", ".rmvb",
                         ".asf", ".vob", ".flv", ".mov")

#: Files the converter writes itself: never copy these over the generated ones.
ASSET_NAME_SKIP = {"config.tjs", "keyconfig.js", "config.tjs.orig"}

#: Folders that are never assets: engine config is written by the converter
#: itself (copying the source's ``system/`` over the generated TyranoScript
#: ``system/`` would break the build - see ASSET_NAME_SKIP for the exception),
#: plus the usual junk a repack leaves behind.
NON_ASSET_DIRS = {
    "scenario", "plugin", "plugins", "k2compat",
    "savedata", "savedata_cn", "mtondata_", "mtdata_", "mtool", "patch",
    "directx", "__macosx",
}


def _asset_kind(fn):
    """Which conversion a source file needs: ``tlg``/``bmp``/``region``/``copy``."""
    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
    if ext == "tlg":
        return "tlg"
    if ext == "bmp":
        return "bmp"
    if _is_region_image(fn):
        return "region"
    return "copy"


def _asset_dest_name(fn):
    """The output file name (``.tlg``/``.bmp`` become ``.png``)."""
    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
    if ext in ("tlg", "bmp"):
        return fn.rsplit(".", 1)[0] + ".png"
    return fn


def _walk_asset_dir(src_dir, out_data, dst_sub):
    """Collect the jobs for one source asset directory (recursive).

    Returns ``(jobs, dropped_video)``; `dst_sub` is the Tyrano folder the whole
    subtree is mapped to, and the sub-path under it is preserved.
    """
    jobs = []
    dropped_video = []

    def _walk(cur, sub, dst_sub=dst_sub):
        # dst_sub is bound as a default: the closure outlives the loop
        # iteration that created it, so reading it from the enclosing
        # scope would see the NEXT sub-directory's value (B023).
        for fn in sorted(os.listdir(cur)):
            sp = os.path.join(cur, fn)
            rel = os.path.join(sub, fn) if sub else fn
            if os.path.isdir(sp):
                _walk(sp, rel)
                continue
            if dst_sub == "system" and fn.lower() in ASSET_NAME_SKIP:
                continue            # the converter writes its own
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if "." + ext in UNPLAYABLE_VIDEO_EXTS:
                dropped_video.append(fn)
                continue
            dst_base = os.path.join(out_data, dst_sub, rel)
            outname = _asset_dest_name(fn)
            if outname != fn:
                dst_path = os.path.join(os.path.dirname(dst_base), outname)
            else:
                dst_path = dst_base
            jobs.append((_asset_kind(fn), sp, dst_path))

    _walk(src_dir, "")
    return jobs, dropped_video


def _walk_root_assets(unpacked, out_data):
    """Collect root-level asset jobs (some repacks keep assets beside scripts).

    Returns ``(jobs, dropped_video, skipped_names)``.
    """
    jobs = []
    dropped_video = []
    skipped = []
    for fn in sorted(os.listdir(unpacked)):
        sp = os.path.join(unpacked, fn)
        if not os.path.isfile(sp):
            continue
        ext = os.path.splitext(fn)[1].lower()
        if ext in UNPLAYABLE_VIDEO_EXTS:
            dropped_video.append(fn)
            continue
        dst_sub = next((sub for sub, exts in ROOT_ASSET_EXTS.items()
                        if ext in exts), None)
        if dst_sub is None:
            skipped.append(fn)
            continue
        jobs.append((_asset_kind(fn), sp,
                     os.path.join(out_data, dst_sub, _asset_dest_name(fn))))
    return jobs, dropped_video, skipped


def _collect_asset_jobs(unpacked, out_data, asset_dirs=None):
    """Walk the source's asset dirs into a flat ``[(kind, src, dst)]`` list.

    KAG3 games name their asset folders inconsistently (``bg`` / ``bgimage`` /
    ``background``, ``se`` / ``sound`` / ``voice``, ``face`` / ``fgimage`` /
    ``frame`` ...) and TyranoScript resolves ``storage=`` *per tag directory*, so
    the destination folder is part of the contract.  The historical hardcoded
    list only knew one game's layout and silently dropped every other folder:
    measured on a real port, 1010 MiB of source became a 166 MiB build (84% of
    the assets lost).  Now:

    * :data:`DEFAULT_ASSET_DIRS` maps the known dialect names to their Tyrano
      folder (``bg`` -> ``bgimage``, ``se`` -> ``sound``, ...);
    * a folder nobody knows is **kept under its own name** instead of dropped
      (so nothing is lost silently) unless it is in :data:`NON_ASSET_DIRS`;
    * a game can override the whole table from its profile (``asset_dirs``),
      because the mapping is per-game data, not tool behaviour.

    KAG3 keeps an asset in exactly one place and TyranoScript resolves
    ``storage=`` per tag directory, so every asset goes to its one canonical
    directory and nowhere else.  The old mirroring (bgimage/fgimage/image copies
    of everything) tripled the build for no benefit - measured: ~75% of the
    duplicated bytes survive compression, so the redundancy was real delivery
    size.

    Collecting first (instead of converting during the walk) is what makes the
    pass parallelisable; the walk itself is cheap metadata I/O.
    """
    mapping = dict(DEFAULT_ASSET_DIRS)
    if asset_dirs:
        mapping.update({k.lower(): v for k, v in asset_dirs.items()})
    jobs = []
    unknown = []
    dropped_video = []
    for src_sub in sorted(os.listdir(unpacked)):
        src_dir = os.path.join(unpacked, src_sub)
        if not os.path.isdir(src_dir):
            continue
        low = src_sub.lower()
        if low in NON_ASSET_DIRS:
            continue                    # scenarios / engine config, handled elsewhere
        dst_sub = mapping.get(low)
        if dst_sub is None:
            dst_sub = src_sub
            unknown.append(src_sub)
        sub_jobs, sub_dropped = _walk_asset_dir(src_dir, out_data, dst_sub)
        jobs += sub_jobs
        dropped_video += sub_dropped

    # Root-level assets: some repacks keep every asset next to the scripts.
    root_jobs, root_dropped, root_skipped = _walk_root_assets(unpacked, out_data)
    jobs += root_jobs
    dropped_video += root_dropped

    if unknown:
        log.warning("asset folder(s) not in the known layout, kept under their "
                    "own name: %s (override with the profile's asset_dirs if "
                    "they belong elsewhere)", ", ".join(sorted(unknown)))
    if root_skipped:
        log.debug("skipped %d root-level non-asset file(s): %s",
                  len(root_skipped), ", ".join(root_skipped[:8]))
    if dropped_video:
        log.warning("dropped %d unplayable raw video file(s) (%s): a browser "
                    "cannot decode them; transcode with tools/transcode_video.py "
                    "and pass --video-dir to ship playable movies",
                    len(dropped_video),
                    ", ".join(sorted({os.path.splitext(f)[1] for f in dropped_video})))
    return jobs


def _convert_assets(unpacked, out_data, stats, workers=None, asset_dirs=None):
    """Copy/convert asset dirs into the Tyrano data/ layout (recursive).

    The image work (TLG/BMP/region -> PNG) is CPU-bound pure Python/PIL, so it
    runs in worker *processes* -- threads would serialise on the GIL (measured:
    0.87 s per TLG image, 658 of them = ~10 min single-threaded).  Copies are
    I/O-bound and go to a thread pool.  Every worker only reports its own
    status and the parent applies `stats` + the WARN lines, so the counters and
    the output bytes do not depend on the worker count.

    `workers=None` auto-tunes from the machine (physical cores, see
    rpgmaker/runtime.py); `workers=1` keeps the historical serial behaviour.
    """
    jobs = _collect_asset_jobs(unpacked, out_data, asset_dirs=asset_dirs)
    image_jobs = [j for j in jobs if j[0] != "copy"]
    copy_jobs = [j for j in jobs if j[0] == "copy"]

    # Create the target directories once, in the parent: workers then only
    # write files, and no two of them race on makedirs.
    for _kind, _src, dst in jobs:
        os.makedirs(os.path.dirname(dst), exist_ok=True)

    workers = runtime.resolve_workers("tlg", workers, path=unpacked)
    if workers <= 1 or len(image_jobs) <= 1:
        for kind, src, dst in image_jobs:
            _apply_image_result(stats, src, dst, *_image_job(src, dst, kind))
    else:
        pool_size = min(workers, len(image_jobs))
        log.debug("asset images: %d job(s) on %d worker process(es)",
                  len(image_jobs), pool_size)
        with ProcessPoolExecutor(max_workers=pool_size) as pool:
            futures = {pool.submit(_image_job, src, dst, kind): (kind, src)
                       for kind, src, dst in image_jobs}
            for fut in as_completed(futures):
                _kind, src = futures[fut]
                _apply_image_result(stats, src, dst, *fut.result())

    if copy_jobs:
        copy_workers = min(runtime.resolve_workers("copy", None, path=unpacked),
                           len(copy_jobs))
        with ThreadPoolExecutor(max_workers=copy_workers) as pool:
            for _ in pool.map(lambda job: shutil.copy2(job[1], job[2]), copy_jobs):
                stats["copied"] += 1


def _decoder_mtime():
    """Newest mtime of the code that decides what a converted image looks
    like.  A cache that only compares source vs target timestamps cannot see a
    decoder fix, so a corrected decoder would silently keep serving images
    built by the old one (measured: the B/R channel-order fix left every
    already-converted PNG red/blue swapped until they were deleted by hand).

    Only the image decoder belongs here.  Including this module would make
    every shim/scenario tweak invalidate all 748 images (~35 min per edit),
    which is the opposite of what the cache is for.
    """
    newest = 0.0
    for path in (getattr(tlg, "__file__", None),):
        if path:
            with contextlib.suppress(OSError):
                newest = max(newest, os.path.getmtime(path))
    return newest


def _up_to_date(src, dst):
    """True when `dst` already exists and is not older than `src`.

    Rebuilding a game re-runs the converter over the whole asset tree, and a
    TLG decode is ~3.3 s per file (658 of them = ~35 min).  Skipping an
    up-to-date target makes a second build cheap, which is what makes it
    practical to iterate on the generated shim/code without paying for the
    image work again.

    Image targets are additionally invalidated when the decoder itself is
    newer than the target, so a decoder fix always regenerates them.
    """
    try:
        t_dst = os.path.getmtime(dst)
    except OSError:
        return False
    try:
        t_src = os.path.getmtime(src)
    except OSError:
        return False
    if t_dst < t_src:
        return False
    return not (dst.lower().endswith(".png") and t_dst < _decoder_mtime())


#: Image conversions are CPU-bound pure Python/PIL work (they hold the GIL),
#: which is why they run in worker *processes* and not in threads.
IMAGE_KINDS = ("tlg", "bmp", "region")

#: WARN text per kind, kept identical to the pre-parallel implementation so a
#: parallel run logs exactly what a serial run logged.
_FAIL_LABEL = {"tlg": "tlg convert failed", "bmp": "bmp convert failed",
               "region": "region convert failed"}


def _image_job(src, dst, kind):
    """Convert one image; returns ``(kind, status, error)``.

    ``status`` is ``"ok"`` / ``"cached"`` / ``"fail"``.  Deliberately does no
    logging and touches no shared counter: a worker process cannot log into
    the parent's stream, and the parent owns `stats` -- so a parallel run
    produces the same counters and the same WARN lines as ``workers=1``.
    """
    if _up_to_date(src, dst):
        return kind, "cached", None
    try:
        if kind == "tlg":
            with open(src, "rb") as f:
                data = f.read()
            tlg.decode_to_png(data, dst)
        else:
            from PIL import Image
            im = Image.open(src)
            if kind == "bmp":
                im.convert("RGBA").save(dst, "PNG")
            elif im.mode == "P":
                # Province image: the palette index is the region number, and
                # gray == index keeps it readable from the R channel.
                Image.frombytes("L", im.size, im.tobytes()).save(dst, "PNG")
            else:
                im.convert("L" if im.mode in ("L", "I") else "RGB").save(dst, "PNG")
        return kind, "ok", None
    except Exception as e:
        # Per-image best-effort fallback: tlg.decode_to_png is a binary format
        # parser, and PIL open/convert/save on arbitrary game assets can raise
        # OSError/ValueError/KeyError/DecompressionBombError etc. - not
        # enumerable, so a failure just counts and continues the conversion.
        return kind, "fail", str(e)


def _apply_image_result(stats, src, dst, kind, status, err):
    """Fold one `_image_job` result into `stats` and the log (parent side).

    `dst` is only used for the WARN line: giving it a root keeps the message
    stable regardless of the process CWD (see `rpgmaker.platform.display_path`).
    """
    if status == "cached":
        stats[f"{kind}_cached"] += 1
    elif status == "ok":
        stats[kind] += 1
    else:
        log.warning("%s %s: %s", _FAIL_LABEL[kind],
                    platform.display_path(src, _asset_root(dst)), err)
        stats[f"{kind}_fail"] += 1


def _asset_root(dst):
    """The data-dir root an asset destination sits in, for log messages.

    Output assets live at ``<data>/<kind>`` (``data/image``, ``data/video``,
    ...), so the grandparent is the data directory.
    """
    return os.path.dirname(os.path.dirname(str(dst)))


def _convert_tlg(src, dst, stats):
    _apply_image_result(stats, src, dst, *_image_job(src, dst, "tlg"))


def _convert_bmp(src, dst, stats):
    _apply_image_result(stats, src, dst, *_image_job(src, dst, "bmp"))
