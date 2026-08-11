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
import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import config  # noqa: E402

log = None  # module logger set in main()

SCRIPT_NAME = "capture_window.ps1"
INTEROP_FIX = (
    "sudo sh -c 'printf \":WSLInterop:M::MZ::/init:P\\n\" "
    "> /proc/sys/fs/binfmt_misc/register'"
)


def powershell_exe():
    """PowerShell interpreter: POWERSHELL_EXE env -> PATH lookup."""
    exe = os.environ.get("POWERSHELL_EXE")
    if exe:
        return exe
    return shutil.which("powershell.exe")


def interop_ok(powershell, binfmt_root="/proc/sys/fs/binfmt_misc"):
    """True when Windows binaries can be executed from WSL.

    An explicit POWERSHELL_EXE override (tests / exotic setups) is trusted.
    Otherwise the kernel must have the WSLInterop binfmt_misc entry.
    """
    if powershell:
        return True
    return os.path.exists(os.path.join(binfmt_root, "WSLInterop"))


def deploy_script(win_temp):
    """Copy tools/capture_window.ps1 to the Windows temp dir when missing or
    stale.  Returns the Windows-form path of the deployed script."""
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), SCRIPT_NAME)
    wsl_dst = os.path.join(config.to_wsl_path(win_temp), SCRIPT_NAME)
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
        "-OutDir", out_dir_win,
    ]
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
    out_dir_win = config.to_windows_path(args.dir)
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


def main(argv=None):
    global log
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--process", help="target process name (without .exe)")
    ap.add_argument("--title", help="window title substring filter")
    ap.add_argument("--out", help="output file name (default <proc>_<ts>.png)")
    ap.add_argument("--dir", default=os.path.join("/mnt", "c", "Users",
                                                  os.environ.get("USER", "user"),
                                                  "Pictures"),
                    help="output directory, WSL form (default /mnt/c/Users/<user>/Pictures)")
    ap.add_argument("--full", action="store_true", help="capture whole screen")
    ap.add_argument("--window-only", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="capture only the window pixels (default)")
    ap.add_argument("--force-visible", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="move window into the visible area first (default)")
    ap.add_argument("--width", type=int, default=0, help="resize width")
    ap.add_argument("--height", type=int, default=0, help="resize height")
    ap.add_argument("--timeout", type=int, default=120,
                    help="powershell timeout in seconds")
    args = ap.parse_args(argv)

    if not args.full and not args.process:
        ap.error("--process is required unless --full")

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

    code, out, err = run_capture(args, powershell)
    if code != 0:
        print(f"error: capture failed (exit {code})", file=sys.stderr)
        if err:
            print(err, file=sys.stderr)
        return 1

    win_path = out[-1]
    wsl_path = config.to_wsl_path(win_path)
    if not os.path.exists(wsl_path):
        print(f"error: output not found: {wsl_path}", file=sys.stderr)
        return 1
    print(wsl_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
