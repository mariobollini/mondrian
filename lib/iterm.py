"""
iTerm2 integration: read current profile colors, write Dynamic Profiles JSON.
"""

import json
import os
import plistlib
import re
import select
import termios
import time
import tty
from pathlib import Path
from typing import Optional

PREFS_PATH = Path("~/Library/Preferences/com.googlecode.iterm2.plist").expanduser()
DYNAMIC_PROFILES_DIR = Path("~/Library/Application Support/iTerm2/DynamicProfiles").expanduser()
PROFILE_FILE = DYNAMIC_PROFILES_DIR / "mondrian.json"

PROFILE_NAMES = {
    "waiting": "Mondrian-Waiting",
    "active":  "Mondrian-Active",
    "blocked": "Mondrian-Blocked",
}


def _srgb_dict(r: float, g: float, b: float) -> dict:
    return {
        "Color Space": "sRGB",
        "Red Component":   r,
        "Green Component": g,
        "Blue Component":  b,
        "Alpha Component": 1.0,
    }


def _query_osc_color(osc_code: int) -> Optional[tuple[float, float, float]]:
    """
    Send an OSC color query (e.g. 10=fg, 11=bg) and return (r,g,b) in [0,1].
    Opens /dev/tty directly so it works even when stdin is redirected.
    Returns None on any failure or timeout.
    """
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return None

    try:
        old = termios.tcgetattr(fd)
        tty.setraw(fd)
        os.write(fd, f"\033]{osc_code};?\007".encode())

        response = b""
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            r, _, _ = select.select([fd], [], [], max(0.0, remaining))
            if not r:
                break
            ch = os.read(fd, 1)
            if not ch:
                break
            response += ch
            if ch == b"\007":
                break
            if len(response) >= 2 and response[-2:] == b"\033\\":
                break
    except Exception:
        response = b""
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass
        os.close(fd)

    text = response.decode("ascii", errors="ignore")
    m = re.search(r"rgb:([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})", text)
    if not m:
        return None

    def parse_channel(s: str) -> float:
        return int(s, 16) / ((1 << (len(s) * 4)) - 1)

    try:
        return (parse_channel(m.group(1)), parse_channel(m.group(2)), parse_channel(m.group(3)))
    except Exception:
        return None


def query_terminal_bg() -> Optional[tuple[float, float, float]]:
    """Query the live terminal background color (OSC 11)."""
    return _query_osc_color(11)


def query_terminal_fg() -> Optional[tuple[float, float, float]]:
    """Query the live terminal foreground color (OSC 10)."""
    return _query_osc_color(10)


def query_terminal_transparency() -> Optional[float]:
    """Query the current iTerm2 session transparency (0=opaque, 1=clear) via AppleScript."""
    import subprocess
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "iTerm2" to transparency of current session of current window'],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return None


def list_profiles() -> list[dict]:
    """Return all iTerm2 profiles, excluding any Mondrian-managed ones."""
    if not PREFS_PATH.exists():
        return []
    with open(PREFS_PATH, "rb") as f:
        prefs = plistlib.load(f)
    return [
        b for b in prefs.get("New Bookmarks", [])
        if not b.get("Name", "").startswith("Mondrian-")
    ]


def read_active_profile() -> Optional[dict]:
    """
    Return the best candidate for the user's working profile (excluding Mondrian profiles).

    Preference order:
    1. The only non-Default profile, if exactly one exists.
    2. The profile marked as Default Bookmark Guid.
    3. The first profile.
    """
    if not PREFS_PATH.exists():
        return None
    with open(PREFS_PATH, "rb") as f:
        prefs = plistlib.load(f)

    # Exclude Mondrian-managed profiles from consideration
    bookmarks = [
        b for b in prefs.get("New Bookmarks", [])
        if not b.get("Name", "").startswith("Mondrian-")
    ]
    if not bookmarks:
        return None

    default_guid = prefs.get("Default Bookmark Guid", "")
    non_default = [b for b in bookmarks if b.get("Guid") != default_guid]
    if len(non_default) == 1:
        return non_default[0]

    for b in bookmarks:
        if b.get("Guid") == default_guid:
            return b
    return bookmarks[0]


def read_profile_colors(profile: Optional[dict] = None) -> dict:
    """
    Return a dict with keys: bg, fg, selbg, selfg (all r,g,b tuples), guid, name.

    bg is taken from the live terminal via OSC 11 query (reflects the actual
    current session color, not just the profile's stored value).  All other
    colors come from the iTerm2 profile plist.
    """
    if profile is None:
        profile = read_active_profile()

    if profile:
        bg_raw    = profile.get("Background Color", {})
        fg_raw    = profile.get("Foreground Color", {})
        selbg_raw = profile.get("Selection Color", {})
        selfg_raw = profile.get("Selected Text Color", {})
        bg = (
            bg_raw.get("Red Component",   0.98),
            bg_raw.get("Green Component", 0.98),
            bg_raw.get("Blue Component",  0.98),
        )
        fg = (
            fg_raw.get("Red Component",   0.063),
            fg_raw.get("Green Component", 0.063),
            fg_raw.get("Blue Component",  0.063),
        )
        selbg = (
            selbg_raw.get("Red Component",   0.702),
            selbg_raw.get("Green Component", 0.843),
            selbg_raw.get("Blue Component",  1.000),
        )
        selfg = (
            selfg_raw.get("Red Component",   0.0),
            selfg_raw.get("Green Component", 0.0),
            selfg_raw.get("Blue Component",  0.0),
        )
        result = {
            "bg":    bg,
            "fg":    fg,
            "selbg": selbg,
            "selfg": selfg,
            "guid":  profile.get("Guid", ""),
            "name":  profile.get("Name", "Default"),
        }
    else:
        result = {
            "bg":    (0.98, 0.98, 0.98),
            "fg":    (0.063, 0.063, 0.063),
            "selbg": (0.702, 0.843, 1.0),
            "selfg": (0.0, 0.0, 0.0),
            "guid":  "",
            "name":  "Unknown",
        }

    # Override bg and fg with live terminal values — captures transparency,
    # manual SetColors calls, or any profile that differs from the plist value.
    actual_bg = query_terminal_bg()
    if actual_bg is not None:
        result["bg"] = actual_bg

    actual_fg = query_terminal_fg()
    if actual_fg is not None:
        result["fg"] = actual_fg

    return result


def write_dynamic_profiles(
    parent_guid: str,
    waiting: tuple,
    active: tuple,
    blocked: tuple,
    fg: tuple,
) -> Path:
    """
    Write (or overwrite) the mondrian Dynamic Profiles JSON.
    Returns the path written.
    """
    DYNAMIC_PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    def profile_entry(state: str, bg: tuple, guid_suffix: str) -> dict:
        entry = {
            "Name": PROFILE_NAMES[state],
            "Guid": f"mondrian-{guid_suffix}",
            "Background Color": _srgb_dict(*bg),
            "Foreground Color": _srgb_dict(*fg),
        }
        if parent_guid:
            entry["Dynamic Profile Parent Name"] = _parent_name_from_guid(parent_guid)
        return entry

    profiles = [
        profile_entry("waiting", waiting, "waiting"),
        profile_entry("active",  active,  "active"),
        profile_entry("blocked", blocked, "blocked"),
    ]

    data = {"Profiles": profiles}
    with open(PROFILE_FILE, "w") as f:
        json.dump(data, f, indent=2)

    return PROFILE_FILE


def _parent_name_from_guid(guid: str) -> str:
    """Look up the profile name for a given Guid."""
    if not PREFS_PATH.exists():
        return ""
    with open(PREFS_PATH, "rb") as f:
        prefs = plistlib.load(f)
    for b in prefs.get("New Bookmarks", []):
        if b.get("Guid") == guid:
            return b.get("Name", "")
    return ""


def remove_dynamic_profiles() -> None:
    if PROFILE_FILE.exists():
        PROFILE_FILE.unlink()
