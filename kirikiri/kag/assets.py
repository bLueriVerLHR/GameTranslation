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
from kirikiri.ks_extract import detect_encoding
from rpgmaker import runtime

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
    try:
        txt = raw.decode(detect_encoding(raw), errors="replace")
    except (UnicodeDecodeError, LookupError):
        # errors="replace" already suppresses decode errors; this guards the
        # theoretical unknown-codec / truncated-input cases only.
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
    _apply_image_result(stats, src, *_image_job(src, dst, "region"))


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
        for fn in fns:
            if fn.lower().endswith(exts):
                found.append(os.path.join(dp, fn))
    if not found:
        return {}

    out_dir = os.path.join(out_data, "video")
    os.makedirs(out_dir, exist_ok=True)
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
    log.info("videos: %d -> %s (+%d raw)", stats["video"], out_dir,
             stats["video_raw"])
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


def _collect_asset_jobs(unpacked, out_data):
    """Walk the mapped asset dirs into a flat ``[(kind, src, dst)]`` list.

    KAG3 games keep an asset in exactly one place and TyranoScript resolves
    `storage=` per tag directory, so every asset goes to its one canonical
    directory and nowhere else.  The old mirroring (bgimage/fgimage/image
    copies of everything) tripled the build for no benefit - measured: ~75% of
    the duplicated bytes survive compression, so the redundancy was real
    delivery size.

    Collecting first (instead of converting during the walk) is what makes the
    pass parallelisable; the walk itself is cheap metadata I/O.
    """
    mapping = [
        ("bgimage", "bgimage"),
        ("fgimage", "fgimage"),
        ("image", "image"),
        ("bgm", "bgm"),
        ("sound", "sound"),
        ("video", "video"),
        ("rule", "fgimage"),
    ]
    jobs = []
    for src_sub, dst_sub in mapping:
        src_dir = os.path.join(unpacked, src_sub)
        if not os.path.isdir(src_dir):
            continue

        def _walk(cur, sub):
            for fn in sorted(os.listdir(cur)):
                sp = os.path.join(cur, fn)
                rel = os.path.join(sub, fn) if sub else fn
                if os.path.isdir(sp):
                    _walk(sp, rel)
                    continue
                ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
                outname = fn
                if ext in ("tlg", "bmp"):
                    outname = fn.rsplit(".", 1)[0] + ".png"
                dst_base = os.path.join(out_data, dst_sub, rel)
                if outname != fn:
                    dst_path = os.path.join(os.path.dirname(dst_base), outname)
                else:
                    dst_path = dst_base
                if ext == "tlg":
                    kind = "tlg"
                elif ext == "bmp":
                    kind = "bmp"
                elif _is_region_image(fn):
                    kind = "region"
                else:
                    kind = "copy"
                jobs.append((kind, sp, dst_path))

        _walk(src_dir, "")
    return jobs


def _convert_assets(unpacked, out_data, stats, workers=None):
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
    jobs = _collect_asset_jobs(unpacked, out_data)
    image_jobs = [j for j in jobs if j[0] != "copy"]
    copy_jobs = [j for j in jobs if j[0] == "copy"]

    # Create the target directories once, in the parent: workers then only
    # write files, and no two of them race on makedirs.
    for _kind, _src, dst in jobs:
        os.makedirs(os.path.dirname(dst), exist_ok=True)

    workers = runtime.resolve_workers("tlg", workers, path=unpacked)
    if workers <= 1 or len(image_jobs) <= 1:
        for kind, src, dst in image_jobs:
            _apply_image_result(stats, src, *_image_job(src, dst, kind))
    else:
        pool_size = min(workers, len(image_jobs))
        log.debug("asset images: %d job(s) on %d worker process(es)",
                  len(image_jobs), pool_size)
        with ProcessPoolExecutor(max_workers=pool_size) as pool:
            futures = {pool.submit(_image_job, src, dst, kind): (kind, src)
                       for kind, src, dst in image_jobs}
            for fut in as_completed(futures):
                _kind, src = futures[fut]
                _apply_image_result(stats, src, *fut.result())

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
            try:
                newest = max(newest, os.path.getmtime(path))
            except OSError:
                pass
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
    if dst.lower().endswith(".png") and t_dst < _decoder_mtime():
        return False
    return True


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


def _apply_image_result(stats, src, kind, status, err):
    """Fold one `_image_job` result into `stats` and the log (parent side)."""
    if status == "cached":
        stats["%s_cached" % kind] += 1
    elif status == "ok":
        stats[kind] += 1
    else:
        log.warning("%s %s: %s", _FAIL_LABEL[kind], os.path.relpath(src), err)
        stats["%s_fail" % kind] += 1


def _convert_tlg(src, dst, stats):
    _apply_image_result(stats, src, *_image_job(src, dst, "tlg"))


def _convert_bmp(src, dst, stats):
    _apply_image_result(stats, src, *_image_job(src, dst, "bmp"))
