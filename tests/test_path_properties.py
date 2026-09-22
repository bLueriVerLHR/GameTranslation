#!/usr/bin/env python3
"""Property tests for the path conversions (PLAN Phase 4 task 9).

The conversions are the load-bearing part of the CRITICAL cross-system rule,
so they are checked as *properties* over generated inputs rather than as a
handful of examples: the example-based tests moved into
``tests/test_platform_paths.py`` and this file explores the space around
them.

Two properties hold exactly, and are the contract callers may rely on:

  * **idempotence** - converting an already-converted path is a no-op;
  * **round-trip stability up to spelling** - ``windows -> wsl -> windows``
    (and back) returns the same *location*, though separators and drive
    letter case are normalized by the first pass, so byte equality does not
    hold and asserting it would be wrong.

Everything else about a path - which side owns it, whether it needs a
Windows tool - is total: :func:`domain_of` and :func:`side_of` accept
anything and never raise.
"""

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from rpgmaker import platform

DRIVE = st.sampled_from("cdefghijklmnopqrstuvwxyz")
SEGMENT = st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ",
                  min_size=1, max_size=12).filter(
    lambda s: s.strip() == s and s not in (".", "..") and "/" not in s
    and "\\" not in s and ":" not in s)
RELATIVE_TAIL = st.lists(SEGMENT, min_size=1, max_size=4)


def _windows(drive, tail):
    return "{}:\\{}".format(drive.upper(), "\\".join(tail))


def _windows_slashes(drive, tail):
    return "{}:/{}".format(drive.upper(), "/".join(tail))


def _wsl_mount(drive, tail):
    return "/mnt/{}/{}".format(drive.lower(), "/".join(tail))


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(drive=DRIVE, tail=RELATIVE_TAIL)
def test_windows_form_to_wsl_and_back_is_stable(drive, tail):
    original = _windows(drive, tail)
    mount = platform.to_wsl_path(original)
    assert mount == _wsl_mount(drive, tail)
    back = platform.to_windows_path(mount)
    # Same location.  Spelling is normalized (backslashes, upper-case drive).
    assert platform.posix(back) == _windows_slashes(drive, tail)
    assert platform.to_wsl_path(back) == mount


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(drive=DRIVE, tail=RELATIVE_TAIL)
def test_mount_root_converts_to_a_drive_root(drive, tail):
    mount = f"/mnt/{drive}"
    assert platform.to_windows_path(mount) == f"{drive.upper()}:\\"
    assert platform.to_wsl_path(f"{drive.upper()}:\\") == mount


@given(path=st.text(max_size=40))
def test_both_conversions_are_idempotent(path):
    once = platform.to_windows_path(path)
    assert platform.to_windows_path(once) == once
    other = platform.to_wsl_path(path)
    assert platform.to_wsl_path(other) == other


@given(path=st.text(max_size=40))
def test_conversion_never_raises_and_never_empties_a_nonempty_path(path):
    for fn in (platform.to_windows_path, platform.to_wsl_path, platform.posix,
               platform.localize, platform.view):
        out = fn(path)
        assert isinstance(out, str)
        assert not path or out  # a non-empty input never collapses to ''


@given(path=st.text(max_size=60))
def test_classification_is_total(path):
    domain = platform.domain_of(path)
    side = platform.side_of(path)
    assert isinstance(domain, platform.PathDomain)
    assert isinstance(side, platform.StorageSide)


@given(drive=DRIVE, tail=RELATIVE_TAIL)
def test_side_classification_follows_the_bytes_not_the_spelling(drive, tail):
    # A /mnt path and its D:\ spelling are the SAME bytes, so both must be
    # reported WINDOWS-side.  Getting this wrong is the CRITICAL bug.
    for spelling in (_windows(drive, tail), _windows_slashes(drive, tail),
                     _wsl_mount(drive, tail)):
        assert platform.side_of(spelling) is platform.StorageSide.WINDOWS
        assert platform.ref(spelling).is_windows


@given(path=st.text(max_size=30))
def test_relative_and_empty_paths_have_no_derivable_side(path):
    # A UNC path is deliberately NOT excluded here at random any more: it has
    # a derivable side (WINDOWS - the bytes live on a Windows share), which is
    # why it is excluded from the property instead.
    assume(platform.domain_of(path) not in (platform.PathDomain.POSIX,
                                            platform.PathDomain.WSL_MOUNT,
                                            platform.PathDomain.WINDOWS_DRIVE,
                                            platform.PathDomain.WINDOWS_UNC))
    assert platform.side_of(path) is platform.StorageSide.NATIVE


def test_a_bare_separator_run_has_no_derivable_side():
    """Regression: ``//`` must not be read as a UNC path.

    A bare separator run names no host, so nothing can be derived from it.
    It used to be classified WINDOWS_UNC (hence WINDOWS-side), which both
    contradicted the property above and would have made a WSL process refuse
    to touch a path that is really just relative.  Two characters were enough
    to reach it, so the property test alone would only have found it by luck.
    """
    for spelling in ("//", "///", "\\\\", "\\\\\\\\", "////"):
        assert platform.domain_of(spelling) is platform.PathDomain.EXOTIC
        assert platform.side_of(spelling) is platform.StorageSide.NATIVE
        assert not platform.ref(spelling).is_windows


def test_a_named_share_is_still_windows_side():
    """The counterpart: a UNC path *with* a host does have a side.

    The converters pass a UNC path through untouched (there is no ``/mnt``
    mount for a share), so the classifier must agree with them and report
    WINDOWS - that is what makes ``require_native_paths`` refuse it under WSL.
    """
    for spelling in ("//host/share", "\\\\host\\share", r"\\host\share\a"):
        assert platform.domain_of(spelling) is platform.PathDomain.WINDOWS_UNC
        assert platform.side_of(spelling) is platform.StorageSide.WINDOWS
        assert platform.to_windows_path(spelling) == spelling
        assert platform.to_wsl_path(spelling) == spelling


@given(tail=st.lists(SEGMENT, min_size=1, max_size=3))
def test_relative_paths_pass_through_unchanged(tail):
    rel = "/".join(tail)
    assert platform.to_windows_path(rel) == rel
    assert platform.to_wsl_path(rel) == rel
    assert platform.domain_of(rel) is platform.PathDomain.RELATIVE


@given(tail=st.lists(SEGMENT, min_size=1, max_size=3))
def test_posix_paths_are_not_mistaken_for_windows_ones(tail):
    p = "/" + "/".join(tail)
    assume(not p.startswith("/mnt/"))
    assert platform.domain_of(p) is platform.PathDomain.POSIX
    assert platform.to_windows_path(p) == p
    assert platform.side_of(p) is platform.StorageSide.POSIX


@given(host=SEGMENT, share=SEGMENT, tail=RELATIVE_TAIL)
def test_unc_paths_survive_unchanged(host, share, tail):
    # A UNC path's ``drive`` is the host/share, not a letter: mapping it into
    # /mnt/<x> would be a bogus mount, so it must pass through untouched.
    unc = "\\\\{}\\{}\\{}".format(host, share, "\\".join(tail))
    assert platform.domain_of(unc) is platform.PathDomain.WINDOWS_UNC
    assert platform.to_wsl_path(unc) == unc
    assert platform.to_windows_path(unc) == unc
    assert platform.side_of(unc) is platform.StorageSide.WINDOWS


@given(name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2,
                    max_size=3))
def test_multi_letter_mnt_segment_is_not_a_drive(name):
    # ``/mnt/cc`` is a directory named cc on a POSIX box, not a Windows mount.
    p = f"/mnt/{name}/x"
    assert platform.domain_of(p) is platform.PathDomain.POSIX
    assert platform.to_windows_path(p) == p


@given(drive=DRIVE, tail=RELATIVE_TAIL)
def test_pathref_keeps_the_original_spelling_and_the_side(drive, tail):
    stored = _windows(drive, tail)
    r = platform.PathRef.parse(stored)
    assert str(r) == stored
    assert r.stored == stored
    assert r.side is platform.StorageSide.WINDOWS
    assert r.domain is platform.PathDomain.WINDOWS_DRIVE
    # The spellings are a pure function of `stored` + the current platform.
    assert r.windows_form() == _windows(drive, tail)
    assert r.wsl_form() == _wsl_mount(drive, tail)
    if platform.is_wsl():
        assert r.view() == r.wsl_form()
    else:
        assert r.view() == platform.posix(stored)


@given(drive=DRIVE, tail=RELATIVE_TAIL)
def test_for_side_is_the_only_spelling_decision(drive, tail):
    r = platform.PathRef.windows(_windows(drive, tail))
    assert r.for_side("win32") == r.windows_form()
    assert r.for_side("native") == r.view()
    # On Windows every local tool IS a Windows tool, so no bridge is needed.
    assert r.needs_windows_tool is not platform.is_windows_os()


def test_the_generator_shapes_are_the_ones_under_test():
    # Guard the generator itself: if the strategies stopped producing both
    # spellings, the properties above would pass vacuously.
    assert platform.posix(r"C:\a\b") == "C:/a/b"
    assert platform.to_wsl_path(r"C:\a\b") == "/mnt/c/a/b"
    assert platform.to_windows_path("/mnt/c/a/b") == r"C:\a\b"
    assert platform.domain_of("\\\\host\\share\\a") \
        is platform.PathDomain.WINDOWS_UNC
    assert platform.domain_of("C:\\a") is platform.PathDomain.WINDOWS_DRIVE
    assert platform.domain_of("/mnt/c/a") is platform.PathDomain.WSL_MOUNT
    assert platform.domain_of("/a/b") is platform.PathDomain.POSIX


@pytest.mark.parametrize("bad", ["", None, "   ", "C:", "/mnt/", "\\\\",
                                 "//host", "\x00nul", "a" * 300])
def test_edge_shapes_never_raise(bad):
    for fn in (platform.domain_of, platform.side_of, platform.to_windows_path,
               platform.to_wsl_path, platform.posix, platform.localize,
               platform.view):
        fn(bad)
    ref = platform.PathRef.parse(bad)
    assert isinstance(ref.side, platform.StorageSide)
    assert isinstance(ref.needs_windows_tool, bool)
