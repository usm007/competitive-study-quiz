"""Cross-platform Desktop Shortcut Automation for StudySynth.

Automatically creates an OS-level desktop shortcut pointing directly to the
master index.html dashboard upon setup or module generation.

Supported platforms:
- Windows (.lnk via PowerShell / WScript.Shell, with .url fallback)
- macOS (.webloc URL bookmark on Desktop)
- Linux (.desktop application entry on Desktop and applications menu)
"""
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path


def get_desktop_dir() -> Path:
    """Resolve the user's Desktop directory across Windows, macOS, and Linux."""
    home = Path.home()

    if sys.platform == "win32":
        # Check standard Windows environment and OneDrive locations
        onedrive = os.environ.get("OneDrive")
        if onedrive and (Path(onedrive) / "Desktop").is_dir():
            return Path(onedrive) / "Desktop"

        userprofile = os.environ.get("USERPROFILE")
        if userprofile and (Path(userprofile) / "Desktop").is_dir():
            return Path(userprofile) / "Desktop"

        # Registry lookup fallback
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            )
            val, _ = winreg.QueryValueEx(key, "Desktop")
            winreg.CloseKey(key)
            expanded = os.path.expandvars(val)
            if Path(expanded).is_dir():
                return Path(expanded)
        except Exception:
            pass

    desktop = home / "Desktop"
    if desktop.is_dir():
        return desktop

    # If ~/Desktop doesn't exist yet, return it anyway or fall back to home
    return desktop if desktop.exists() else home


def _create_windows_url_fallback(target_file: Path, url_path: Path) -> Path | None:
    """Create Windows Internet Shortcut (.url) as fallback."""
    try:
        file_url = target_file.resolve().as_uri()
        url_content = f"[InternetShortcut]\nURL={file_url}\nIconIndex=0\n"
        url_path.write_text(url_content, encoding="utf-8")
        return url_path
    except Exception as e:
        print(f"WARNING: Windows shortcut creation fallback error: {e}", file=sys.stderr)
        return None


def _create_windows_shortcut(target_file: Path, shortcut_name: str, desktop: Path) -> Path | None:
    """Create Windows .lnk shortcut via PowerShell, with .url fallback."""
    lnk_path = desktop / f"{shortcut_name}.lnk"
    url_path = desktop / f"{shortcut_name}.url"

    target_abs = str(target_file.resolve())

    # Try PowerShell WScript.Shell
    ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{str(lnk_path)}')
$Shortcut.TargetPath = '{target_abs}'
$Shortcut.Description = 'StudySynth Master Study Library'
$Shortcut.WorkingDirectory = '{str(target_file.parent.resolve())}'
$Shortcut.Save()
"""
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode == 0 and lnk_path.is_file():
            return lnk_path
    except Exception:
        pass

    # Fallback to Internet Shortcut (.url)
    return _create_windows_url_fallback(target_file, url_path)


def _create_macos_shortcut(target_file: Path, shortcut_name_or_path: str | Path, desktop: Path | None = None) -> Path | None:
    """Create macOS .webloc URL bookmark pointing to file URI."""
    if isinstance(shortcut_name_or_path, Path):
        webloc_path = shortcut_name_or_path
    else:
        webloc_path = (desktop or get_desktop_dir()) / f"{shortcut_name_or_path}.webloc"
    file_url = target_file.resolve().as_uri()
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>URL</key>
    <string>{file_url}</string>
</dict>
</plist>
"""
    try:
        webloc_path.write_text(content, encoding="utf-8")
        return webloc_path
    except Exception as e:
        print(f"WARNING: macOS shortcut creation error: {e}", file=sys.stderr)
        return None


def _create_linux_shortcut(target_file: Path, shortcut_name_or_path: str | Path, display_name: str = "StudySynth Library", desktop: Path | None = None) -> Path | None:
    """Create Linux .desktop launcher entry."""
    if isinstance(shortcut_name_or_path, Path):
        entry_path = shortcut_name_or_path
    else:
        entry_path = (desktop or get_desktop_dir()) / f"{shortcut_name_or_path.lower().replace(' ', '-')}.desktop"
    file_url = target_file.resolve().as_uri()
    content = f"""[Desktop Entry]
Version=1.0
Type=Link
Name={display_name}
Comment=StudySynth Master Study Library & Revision Engine
URL={file_url}
Icon=system-help
Terminal=false
Categories=Education;
"""
    try:
        entry_path.write_text(content, encoding="utf-8")
        entry_path.chmod(0o755)
        return entry_path
    except Exception as e:
        print(f"WARNING: Linux shortcut creation error: {e}", file=sys.stderr)
        return None


def create_desktop_shortcut(
    dashboard_path: Path | str,
    shortcut_name: str = "StudySynth Library",
    desktop_dir: Path | str | None = None,
    name: str | None = None,
) -> Path | None:
    """Create a desktop shortcut pointing to the specified dashboard HTML file.

    Args:
        dashboard_path: Path to the master index.html file
        shortcut_name: Human-friendly name for the shortcut (default 'StudySynth Library')
        desktop_dir: Optional custom directory to place the shortcut (defaults to user Desktop)
        name: Optional alias for shortcut_name

    Returns:
        Path to the created shortcut file, or None if creation failed.
    """
    final_name = name or shortcut_name or "StudySynth Library"
    target = Path(dashboard_path).resolve()
    if not target.is_file():
        # Ensure parent exists so target can be referenced
        target.parent.mkdir(parents=True, exist_ok=True)

    desktop = Path(desktop_dir).resolve() if desktop_dir else get_desktop_dir()
    desktop.mkdir(parents=True, exist_ok=True)

    plat = sys.platform
    created: Path | None = None

    if plat == "win32":
        created = _create_windows_shortcut(target, final_name, desktop)
    elif plat == "darwin":
        created = _create_macos_shortcut(target, final_name, desktop)
    else:  # Linux and other Unixes
        created = _create_linux_shortcut(target, final_name, final_name, desktop)

    return created


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate OS-level desktop shortcut for StudySynth Library.")
    ap.add_argument("--dashboard", "-d", default="output/index.html", help="Path to master index.html")
    ap.add_argument("--name", "-n", default="StudySynth Library", help="Shortcut display name")
    ap.add_argument("--desktop-dir", default=None, help="Custom directory for shortcut (defaults to Desktop)")
    args = ap.parse_args(argv)

    created = create_desktop_shortcut(args.dashboard, args.name, args.desktop_dir)
    if created:
        print(f"OK: Created desktop shortcut at {created}")
        return 0
    else:
        print("ERROR: Failed to create desktop shortcut", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
