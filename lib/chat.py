"""
Interactive palette picker — no API key required.

Shows the auto-derived directions, lets the user pick one, then optionally
override individual hex values. For freeform color tweaking, just describe
what you want to change in Claude Code and re-run `mondrian configure`.
"""

import sys
from .colors import derive_palette, preview_all_directions, preview_palette, hex_to_srgb, srgb_to_hex


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


def pick_direction_interactively(
    bg: tuple,
    fg: tuple,
) -> tuple[tuple, tuple, tuple, str]:
    """
    Show derived directions, pick one, optionally tweak hex values.
    Returns (waiting, active, blocked, label).
    """
    directions = derive_palette(bg)

    print("\n  Derived palette directions from your terminal background:\n")
    print(preview_all_directions(directions, fg=fg))
    print()
    print("  Tip: not quite right? Describe the change in Claude Code and re-run configure.\n")

    choice = None
    while choice not in directions:
        try:
            raw = input("  Pick a direction [A/B/C/D], or Enter for A: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            raw = ""
        choice = raw if raw in directions else "A"

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

    return waiting, active, blocked, label
