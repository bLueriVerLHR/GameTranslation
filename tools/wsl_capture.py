#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wsl_capture.py - window-targeted screenshot of a Windows app from WSL.

Wraps tools/capture_window.ps1 (window-level capture: the script finds the
target window by process name, optionally filters by window title substring,
moves it fully into the visible area and captures the window's own pixels
with PrintWindow, so the shot is precise and occlusion-immune).

Flow:
  1. Check WSL interop (the WSLInterop binfmt entry must exist; otherwise
     give the exact re-registration command).
  2. Deploy capture_window.ps1 to the Windows temp dir (idempotent).
  3. Convert the output dir to Windows form and invoke powershell.exe.
  4. Map the printed output path back to WSL form and verify it exists.

Usage:
  python wsl_capture.py --process GamePro [--title 確認] [--out shot.png]
                        [--dir /mnt/c/Users/<user>/Pictures] [--full]
                        [--window-only] [--force-visible] [--width N] [--height N]

Exit codes: 0 = captured; 1 = no window/error; 2 = interop missing.
The WSL-side path of the saved PNG is printed on success.
"""
import logging
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace
from typing import Annotated, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402
from rpgmaker import config  # noqa: E402

log = logging.getLogger("wsl_capture")

BINFMT_ROOT = "/proc/sys/fs/binfmt_misc"
SCRIPT_NAME = "capture_window.ps1"
INTEROP_FIX = (
    "sudo sh -c 'printf \":WSLInterop:M::MZ::/init:P\\n\" "
    "> /proc/sys/fs/binfmt_misc/register'"
)


def powershell_exe():
    """PowerShell interpreter for this platform: POWERSHELL_EXE env ->
    env_config -> probe -> PATH (see rpgmaker.config.resolve_tool)."""
    return config.find_powershell()


def interop_ok(powershell, binfmt_root=BINFMT_ROOT):
    """True when a Windows binary can actually be executed from here.

    An explicit POWERSHELL_EXE override (tests / exotic setups) is trusted,
    native Windows always can, and WSL needs the kernel's WSLInterop
    binfmt_misc entry - without it a found powershell.exe path is unusable
    and the caller prints the re-registration command.
    """
    if os.environ.get("POWERSHELL_EXE"):
        return True
    if not config.is_wsl():
        return bool(powershell)
    return os.path.exists(os.path.join(binfmt_root, "WSLInterop"))


def deploy_script(win_temp):
    """Copy tools/capture_window.ps1 to the Windows temp dir when missing or
    stale.  Returns the Windows-form path of the deployed script."""
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), SCRIPT_NAME)
    wsl_dst = os.path.join(config.localize(win_temp), SCRIPT_NAME)
    stale = (not os.path.exists(wsl_dst)
             or os.path.getmtime(wsl_dst) < os.path.getmtime(src))
    if stale:
        os.makedirs(os.path.dirname(wsl_dst), exist_ok=True)
        shutil.copy2(src, wsl_dst)
    return config.to_windows_path(wsl_dst)


def build_args(args, out_dir_win, script_win):
    """Assemble the powershell.exe command line for the capture script."""
    cmd = [
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_win,
    ]
    if args.dir:
        cmd += ["-OutDir", out_dir_win]
    if args.full:
        cmd.append("-Full")
    else:
        cmd.append("-ProcessName")
        cmd.append(args.process)
    if args.title:
        cmd += ["-Title", args.title]
    if args.out:
        cmd += ["-Out", args.out]
    if not args.window_only:
        cmd.append("-WindowOnly:$false")
    if not args.force_visible:
        cmd.append("-ForceVisible:$false")
    if args.width:
        cmd += ["-Width", str(args.width)]
    if args.height:
        cmd += ["-Height", str(args.height)]
    return cmd


def run_capture(args, powershell):
    """Deploy + invoke powershell; return (exit_code, output_lines)."""
    win_temp = config.win_temp_dir()
    script_win = deploy_script(win_temp)
    out_dir_win = config.to_windows_path(args.dir) if args.dir else None
    cmd = [powershell] + build_args(args, out_dir_win, script_win)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
    out = [line.strip() for line in (r.stdout or "").splitlines()
           if line.strip()]
    err = "\n".join(line for line in (r.stderr or "").splitlines()
                    if line.strip())
    if r.returncode != 0:
        return r.returncode, out, err
    if not out:
        return 1, out, err or "capture script printed no output path"
    return 0, out, err


def cmd(process: Annotated[Optional[str], cliutil.Option(
            "--process", help="target process name (without .exe)")] = None,
        title: Annotated[Optional[str], cliutil.Option(
            "--title", help="window title substring filter")] = None,
        out: Annotated[Optional[str], cliutil.Option(
            "--out", help="output file name (default <proc>_<ts>.png)")] = None,
        out_dir: Annotated[Optional[str], cliutil.Option(
            "--dir", help="output directory, WSL form (default: the Windows "
            "user's Pictures folder)")] = None,
        full: Annotated[bool, cliutil.Option(
            "--full", help="capture whole screen")] = False,
        window_only: Annotated[bool, cliutil.Option(
            "--window-only/--no-window-only",
            help="capture only the window pixels (default)")] = True,
        force_visible: Annotated[bool, cliutil.Option(
            "--force-visible/--no-force-visible",
            help="move window into the visible area first (default)")] = True,
        width: Annotated[int, cliutil.Option(
            "--width", help="resize width")] = 0,
        height: Annotated[int, cliutil.Option(
            "--height", help="resize height")] = 0,
        timeout: Annotated[int, cliutil.Option(
            "--timeout", help="powershell timeout in seconds")] = 120,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)

    if not full and not process:
        print("--process is required unless --full", file=sys.stderr)
        return 2

    options = SimpleNamespace(
        process=process, title=title, out=out, dir=out_dir, full=full,
        window_only=window_only, force_visible=force_visible,
        width=width, height=height, timeout=timeout,
    )

    powershell = powershell_exe()
    if not powershell:
        print("error: powershell.exe not found (is this WSL?)", file=sys.stderr)
        return 2
    if not interop_ok(powershell):
        print("error: WSL interop is not registered "
              "(/proc/sys/fs/binfmt_misc/WSLInterop missing).", file=sys.stderr)
        print("restore it with:", file=sys.stderr)
        print("  " + INTEROP_FIX, file=sys.stderr)
        return 2

    code, out_lines, err = run_capture(options, powershell)
    if code != 0:
        print(f"error: capture failed (exit {code})", file=sys.stderr)
        if err:
            print(err, file=sys.stderr)
        return 1

    win_path = out_lines[-1]
    local_path = config.localize(win_path)
    if not os.path.exists(local_path):
        print(f"error: output not found: {local_path}", file=sys.stderr)
        return 1
    print(local_path)
    return 0


app = cliutil.command_app(cmd, help=__doc__)
# argparse used the module docstring as the command description; keep that
# visible in --help (a collapsed single-command app shows the command help).
cmd.__doc__ = __doc__


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="wsl_capture.py")


if __name__ == "__main__":
    raise SystemExit(main())
