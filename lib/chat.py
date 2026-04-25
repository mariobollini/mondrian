"""
Interactive palette picker — no API key required.

Shows the auto-derived directions, lets the user pick one, then optionally
override individual hex values. For freeform color tweaking, just describe
what you want to change in Claude Code and re-run `mondrian configure`.
"""

import os
import sys
from .colors import (
    derive_palette, preview_all_directions, preview_palette,
    hex_to_srgb, srgb_to_hex,
    load_itermcolors, scan_itermcolors,
)
from .fetch import SCHEMES_DIR, copy_to_library, list_local_schemes

DEFAULT_SCAN_DIRS = ["~/Downloads", "~/Documents", "~/Desktop"]


# ---------------------------------------------------------------------------
# Path tab-completion
# ---------------------------------------------------------------------------

def _setup_path_completer() -> None:
    """Enable filesystem tab-completion for the current readline session."""
    try:
        import readline
        import glob

        def completer(text, state):
            expanded = os.path.expanduser(text)
            matches = [
                m + ("/" if os.path.isdir(m) else "")
                for m in sorted(glob.glob(expanded + "*"))
            ]
            if text.startswith("~"):
                home = os.path.expanduser("~")
                matches = [
                    "~" + m[len(home):] if m.startswith(home) else m
                    for m in matches
                ]
            return matches[state] if state < len(matches) else None

        readline.set_completer(completer)
        readline.set_completer_delims(" \t\n;")
        readline.parse_and_bind("tab: complete")
    except Exception:
        pass


def _teardown_completer() -> None:
    try:
        import readline
        readline.set_completer(None)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Shared prompt helpers
# ---------------------------------------------------------------------------

def _prompt_hex(label: str, current: tuple) -> tuple:
    """Ask the user for a hex override. Empty input keeps the current value."""
    current_hex = srgb_to_hex(*current)
    try:
        raw = input(f"  {label} [{current_hex}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return current
    if not raw:
        return current
    raw = raw if raw.startswith("#") else f"#{raw}"
    if len(raw) != 7:
        print(f"  Invalid hex, keeping {current_hex}")
        return current
    try:
        return hex_to_srgb(raw)
    except ValueError:
        print(f"  Invalid hex, keeping {current_hex}")
        return current


# ---------------------------------------------------------------------------
# Custom .itermcolors picker
# ---------------------------------------------------------------------------

def _show_scheme_list(schemes: list[tuple[str, str]], start: int = 1) -> None:
    for i, (name, _) in enumerate(schemes, start=start):
        print(f"    {i:2d}. {name}")


def _pick_one_scheme(schemes: list[tuple[str, str]], label: str) -> dict:
    """Pick a single scheme by number; returns its loaded color dict."""
    while True:
        try:
            raw = input(f"  {label} [1-{len(schemes)}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            raw = "1"
        if not raw:
            raw = "1"
        try:
            idx = int(raw) - 1
        except ValueError:
            print(f"  Enter a number between 1 and {len(schemes)}.")
            continue
        if not (0 <= idx < len(schemes)):
            print(f"  Enter a number between 1 and {len(schemes)}.")
            continue
        name, path = schemes[idx]
        try:
            return load_itermcolors(path)
        except Exception as e:
            print(f"  Could not load {name}: {e}")


def pick_custom_interactively() -> tuple[dict, dict, dict]:
    """
    Guide the user through selecting three .itermcolors schemes.
    Returns (waiting_colors, active_colors, blocked_colors), each a
    {bg, fg, bold, selbg, selfg} hex dict.
    """
    _setup_path_completer()
    try:
        return _pick_custom_inner()
    finally:
        _teardown_completer()


def _pick_custom_inner() -> tuple[dict, dict, dict]:
    print("\n  Custom .itermcolors mode")
    print("  " + "─" * 42)

    # Library first, then default dirs — library schemes appear at top of list
    all_scan_dirs = [str(SCHEMES_DIR)] + DEFAULT_SCAN_DIRS
    library_names = {n for n, _ in list_local_schemes()}

    print(f"\n  Scanning library + {', '.join(DEFAULT_SCAN_DIRS)} …")
    schemes = scan_itermcolors(all_scan_dirs)

    if schemes:
        print(f"  Found {len(schemes)} scheme{'s' if len(schemes) != 1 else ''}:\n")
        _show_scheme_list(schemes)
    else:
        print("  No .itermcolors files found. Run: mondrian fetch --all")

    # Optional extra directory
    print()
    try:
        extra = input("  Scan another directory? [path or Enter to skip]: ").strip()
    except (EOFError, KeyboardInterrupt):
        extra = ""

    if extra:
        extra_schemes = scan_itermcolors([extra])
        existing_names = {n for n, _ in schemes}
        new = [(n, p) for n, p in extra_schemes if n not in existing_names]
        if new:
            start = len(schemes) + 1
            print(f"\n  Found {len(new)} more:\n")
            _show_scheme_list(new, start=start)
            schemes = schemes + new

            # Offer to copy new finds into the library
            outside_library = [(n, p) for n, p in new if n not in library_names]
            if outside_library:
                print()
                try:
                    raw = input(f"  Copy {len(outside_library)} new scheme(s) to your local library? [Y/n]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    raw = ""
                if raw != "n":
                    for _, p in outside_library:
                        copy_to_library(p)
                    print(f"  Saved to {SCHEMES_DIR}")
        else:
            print("  No new schemes found there.")

    if not schemes:
        print("\n  No schemes found. Run: mondrian fetch --all\n")
        sys.exit(1)

    print()
    waiting_colors = _pick_one_scheme(schemes, "Waiting  (your normal state)  ")
    active_colors  = _pick_one_scheme(schemes, "Active   (Claude is working)  ")
    blocked_colors = _pick_one_scheme(schemes, "Blocked  (Claude needs input) ")

    # Preview
    print(preview_palette(
        "  Custom palette",
        hex_to_srgb(waiting_colors["bg"]),
        hex_to_srgb(active_colors["bg"]),
        hex_to_srgb(blocked_colors["bg"]),
        fg=hex_to_srgb(waiting_colors["fg"]),
    ))
    print()

    return waiting_colors, active_colors, blocked_colors


# ---------------------------------------------------------------------------
# Main direction picker
# ---------------------------------------------------------------------------

def pick_direction_interactively(
    bg: tuple,
    fg: tuple,
) -> tuple:
    """
    Show derived directions A–D plus E (custom), pick one.

    Returns a 5-tuple:
      (waiting_rgb, active_rgb, blocked_rgb, label, custom_colors)

    For A–D: custom_colors is None; waiting/active/blocked are (r,g,b) float tuples.
    For E:   waiting/active/blocked are None; custom_colors is
             {"waiting": {...hex dict...}, "active": {...}, "blocked": {...}}.
    """
    directions = derive_palette(bg)

    print("\n  Derived palette directions from your terminal background:\n")
    print(preview_all_directions(directions, fg=fg))
    print()
    print("  [E] Load custom .itermcolors files\n")
    print("  Tip: not quite right? Describe the change in Claude Code and re-run configure.\n")

    valid = set(directions.keys()) | {"E"}
    choice = None
    while choice not in valid:
        try:
            raw = input("  Pick a direction [A/B/C/D/E], or Enter for A: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            raw = ""
        choice = raw if raw in valid else "A"

    if choice == "E":
        w, a, b = pick_custom_interactively()
        return None, None, None, "custom", {"waiting": w, "active": a, "blocked": b}

    d = directions[choice]
    waiting = d["waiting"]
    active  = d["active"]
    blocked = d["blocked"]
    label   = d["label"]

    print(preview_palette(f"  [{choice}] {label}", waiting, active, blocked, fg=fg))
    if choice == "D":
        print("  (Waiting and Active share the same background — opacity is the signal.)")
    print()

    try:
        want_override = input("  Override any colors? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        want_override = ""

    if want_override == "y":
        print("  Enter hex values to override (press Enter to keep current):\n")
        if choice != "D":
            active = _prompt_hex("Active ", active)
        blocked = _prompt_hex("Blocked", blocked)
        print()
        print(preview_palette("  Final palette", waiting, active, blocked, fg=fg))
        print()

    return waiting, active, blocked, label, None
