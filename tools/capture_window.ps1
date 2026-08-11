# capture_window.ps1 - window-targeted screenshot for a specific app.
#
# Finds a top-level window of the given process (optionally filtered by a
# title substring), restores it if minimized, moves it fully into the
# visible screen area (modal dialog buttons often sit below the screen
# edge), then captures the window's own pixels with PrintWindow (immune to
# occlusion - a covered window still captures correctly). Falls back to a
# screen copy when PrintWindow is unsupported.
#
# Usage (from WSL via tools/wsl_capture.py, or directly):
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File capture_window.ps1 ^
#     -ProcessName GamePro [-Title '確認'] [-OutDir %USERPROFILE%\Pictures] ^
#     [-Out shot.png] [-Full] [-WindowOnly:$false] [-ForceVisible:$false] ^
#     [-Width 1280] [-Height 720]
#
# Exit codes: 0 = saved; 1 = target window not found; 2 = capture failed.
# The absolute output path is printed to stdout on success.
#
# Output is always UTF-8 so non-ASCII paths survive the WSL round trip.

param(
    [string]$ProcessName,
    [string]$Title,
    [string]$OutDir,
    [string]$Out,
    [switch]$Full,
    [bool]$WindowOnly = $true,
    [bool]$ForceVisible = $true,
    [int]$Width = 0,
    [int]$Height = 0
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class CapApi {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd, int x, int y, int w, int h, bool repaint);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool GetWindowPlacement(IntPtr hWnd, ref WINDOWPLACEMENT placement);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] public struct WINDOWPLACEMENT {
        public int length, flags, showCmd;
        public POINT ptMinPosition, ptMaxPosition;
        public RECT rcNormalPosition;
    }
}
"@

# ------------------------------------------------------------------ helpers

function Get-TargetWindow {
    # Enumerate visible top-level windows of $ProcessName; filter by title
    # substring when given; return the largest (by area) candidate.
    param([string]$ProcessName, [string]$Title)
    $proc = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $proc) { return $null }
    $targetPid = $proc.Id
    $windows = New-Object System.Collections.ArrayList
    $cb = [CapApi+EnumProc]{
        param($hWnd, $lParam)
        $wpid = 0
        [CapApi]::GetWindowThreadProcessId($hWnd, [ref]$wpid) | Out-Null
        if ($wpid -eq $targetPid -and [CapApi]::IsWindowVisible($hWnd)) {
            $sb = New-Object System.Text.StringBuilder 512
            [CapApi]::GetWindowText($hWnd, $sb, 512) | Out-Null
            $r = New-Object CapApi+RECT
            [CapApi]::GetWindowRect($hWnd, [ref]$r) | Out-Null
            $null = $windows.Add([PSCustomObject]@{
                Hwnd = $hWnd
                Title = $sb.ToString()
                L = $r.Left; T = $r.Top; R = $r.Right; B = $r.Bottom
            })
        }
        return $true
    }
    [CapApi]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
    if ($windows.Count -eq 0) { return $null }
    $byArea = { ($_.R - $_.L) * ($_.B - $_.T) }
    if ($Title) {
        $hit = $windows | Where-Object { $_.Title.Contains($Title) } |
            Sort-Object $byArea -Descending | Select-Object -First 1
        if ($hit) { return $hit }
    }
    return $windows | Sort-Object $byArea -Descending | Select-Object -First 1
}

function Assert-WindowOnScreen {
    # Restore minimized windows and move the window fully into the visible
    # bounds of the screen it occupies.
    param($Win)
    $placement = New-Object CapApi+WINDOWPLACEMENT
    $placement.length = [System.Runtime.InteropServices.Marshal]::SizeOf($placement)
    [CapApi]::GetWindowPlacement($Win.Hwnd, [ref]$placement) | Out-Null
    if ($placement.showCmd -eq 2) {  # SW_SHOWMINIMIZED
        [CapApi]::ShowWindow($Win.Hwnd, 9) | Out-Null  # SW_RESTORE
        Start-Sleep -Milliseconds 400
    }
    $r = New-Object CapApi+RECT
    [CapApi]::GetWindowRect($Win.Hwnd, [ref]$r) | Out-Null
    $w = $r.Right - $r.Left
    $h = $r.Bottom - $r.Top
    if ($w -le 0 -or $h -le 0) { return $null }
    if (-not $ForceVisible) {
        return [PSCustomObject]@{ Hwnd = $Win.Hwnd; L = $r.Left; T = $r.Top; R = $r.Right; B = $r.Bottom }
    }
    $scr = [System.Windows.Forms.Screen]::FromRectangle(
        [System.Drawing.Rectangle]::FromLTRB($r.Left, $r.Top, $r.Right, $r.Bottom))
    $bx = $scr.Bounds.X; $by = $scr.Bounds.Y
    $bw = $scr.Bounds.Width; $bh = $scr.Bounds.Height
    $x = [Math]::Min([Math]::Max($r.Left, $bx), $bx + $bw - [Math]::Min($w, $bw))
    $y = [Math]::Min([Math]::Max($r.Top, $by), $by + $bh - [Math]::Min($h, $bh))
    if ($x -ne $r.Left -or $y -ne $r.Top) {
        [CapApi]::MoveWindow($Win.Hwnd, $x, $y, $w, $h, $true) | Out-Null
        Start-Sleep -Milliseconds 400
        [CapApi]::GetWindowRect($Win.Hwnd, [ref]$r) | Out-Null
    }
    return [PSCustomObject]@{ Hwnd = $Win.Hwnd; L = $r.Left; T = $r.Top; R = $r.Right; B = $r.Bottom }
}

function Save-Bitmap {
    param([System.Drawing.Bitmap]$Bmp, [string]$OutDir, [string]$Out, [string]$ProcessName)
    if (-not $OutDir) { $OutDir = Join-Path $env:USERPROFILE 'Pictures' }
    if (-not (Test-Path $OutDir)) {
        New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    }
    if (-not $Out) {
        $base = 'screen'
        if ($ProcessName) { $base = $ProcessName }
        $Out = '{0}_{1}.png' -f $base, (Get-Date -Format 'yyyyMMdd_HHmmss')
    }
    $path = Join-Path $OutDir $Out
    $Bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Output $path
}

# ------------------------------------------------------------------ capture

try {
    if ($Full) {
        # Whole primary screen (context shot when the target is unknown).
        $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
        $g.Dispose()
        Save-Bitmap -Bmp $bmp -OutDir $OutDir -Out $Out -ProcessName ''
        $bmp.Dispose()
        exit 0
    }

    if (-not $ProcessName) {
        Write-Error 'Either -ProcessName or -Full is required.'
        exit 2
    }

    $win = Get-TargetWindow -ProcessName $ProcessName -Title $Title
    if (-not $win) {
        Write-Error "No visible window found for process '$ProcessName'"
        exit 1
    }

    $rect = Assert-WindowOnScreen -Win $win
    if (-not $rect) {
        Write-Error "Window for '$ProcessName' has empty bounds"
        exit 1
    }
    $cw = $rect.R - $rect.L
    $ch = $rect.B - $rect.T

    $bmp = New-Object System.Drawing.Bitmap $cw, $ch
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $g.GetHdc()
    $ok = $false
    if ($WindowOnly) {
        # PW_RENDERFULLCONTENT (2) first: captures DirectX/OpenGL content on
        # modern Windows; fall back to the classic whole-window capture.
        $ok = [CapApi]::PrintWindow($rect.Hwnd, $hdc, 2)
        if (-not $ok) { $ok = [CapApi]::PrintWindow($rect.Hwnd, $hdc, 0) }
    }
    $g.ReleaseHdc($hdc)
    $g.Dispose()
    if (-not $ok) {
        # PrintWindow unsupported: copy the window region from the screen.
        $bmp.Dispose()
        $bmp = New-Object System.Drawing.Bitmap $cw, $ch
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($rect.L, $rect.T, 0, 0,
            (New-Object System.Drawing.Size $cw, $ch))
        $g.Dispose()
    }

    if ($Width -gt 0 -and $Height -gt 0) {
        $scaled = New-Object System.Drawing.Bitmap $Width, $Height
        $sg = [System.Drawing.Graphics]::FromImage($scaled)
        $sg.DrawImage($bmp, 0, 0, $Width, $Height)
        $sg.Dispose()
        $bmp.Dispose()
        $bmp = $scaled
    }

    Save-Bitmap -Bmp $bmp -OutDir $OutDir -Out $Out -ProcessName $ProcessName
    $bmp.Dispose()
    exit 0
}
catch {
    Write-Error $_
    exit 2
}
