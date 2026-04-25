"""
Interactive palette picker — no API key required.

Shows the auto-derived directions, lets the user pick one, then optionally
override individual hex values. For freeform color tweaking, just describe
what you want to change in Claude Code and re-run `mondrian configure`.
"""

import sys
from .colors import (
    derive_palette, preview_all_directions, preview_palette,
    hex_to_srgb, srgb_to_hex,
    load_itermcolors,
)
from .fetch import SCHEMES_DIR, list_local_schemes, load_favorites


# ---------------------------------------------------------------------------
# Scheme list helpers
# ---------------------------------------------------------------------------

def _get_all_schemes() -> tuple[list[tuple[str, object]], set[str]]:
    """
    Return (schemes, favorites) where schemes is [(name, path_or_colors_dict), ...].

    Sources (in priority order, deduplicated by name):
      1. ~/.mondrian/schemes/*.itermcolors  (path strings)
      2. iTerm2 Custom Color Presets from plist  (pre-loaded dicts)

    favorites-first sort: starred items float to the top, then alphabetical.
    """
    from .iterm import list_color_presets

    favorites = load_favorites()

    local   = list_local_schemes()               # [(name, path_str), ...]
    presets = list_color_presets()               # [(name, colors_dict), ...]

    local_names = {n for n, _ in local}
    combined = local + [(n, d) for n, d in presets if n not in local_names]

    def sort_key(item):
        name = item[0]
        return (0 if name in favorites else 1, name.lower())

    return sorted(combined, key=sort_key), favorites


def _pick_scheme_via_browser(prompt: str) -> dict | None:
    """
    Open the full-screen browser in select mode. Returns the selected colors
    dict or None if the user cancelled. Favorites are shown first.
    """
    from .browse import run_browser

    schemes, favorites = _get_all_schemes()
    if not schemes:
        return None

    return run_browser(
        schemes, favorites, load_itermcolors,
        select_mode=True, prompt=prompt,
    )


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
# Custom .itermcolors picker (Direction E)
# ---------------------------------------------------------------------------

def pick_custom_interactively() -> tuple[dict, dict, dict]:
    """
    Guide the user through selecting three schemes via the browse TUI.
    Returns (waiting_colors, active_colors, blocked_colors), each a
    {bg, fg, bold, selbg, selfg} hex dict.
    """
    schemes, _ = _get_all_schemes()
    if not schemes:
        print("\n  No schemes found. Run: mondrian fetch --all\n")
        sys.exit(1)

    print(f"\n  {len(schemes)} schemes available — use ↑↓ to navigate, Enter to select.\n")

    def pick(label: str) -> dict:
        print(f"  Select: {label}")
        colors = _pick_scheme_via_browser(label)
        if colors is None:
            print("  Cancelled.")
            sys.exit(0)
        return colors

    waiting_colors = pick("Waiting  (your normal state) ")
    active_colors  = pick("Active   (Claude is working) ")
    blocked_colors = pick("Blocked  (Claude needs input)")

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
    Optionally rederive palette from an iTerm2 scheme, then show A–D + E.

    Returns a 6-tuple:
      (waiting_rgb, active_rgb, blocked_rgb, label, custom_colors, base_overrides)

    For A–D from terminal:  custom_colors=None, base_overrides=None
    For A–D from scheme:    custom_colors=None, base_overrides={"fg","selbg","selfg"} hex strs
    For E (custom):         waiting/active/blocked=None, custom_colors={...}, base_overrides=None
    """
    # -----------------------------------------------------------------------
    # Step 0: Ask whether to base palette on current terminal or a scheme
    # -----------------------------------------------------------------------
    schemes, _ = _get_all_schemes()
    base_overrides = None

    if schemes:
        print()
        try:
            raw = input(
                "  Derive palette from  [1] current terminal  [2] iTerm2 scheme: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            raw = "1"
        if raw == "2":
            print("  Pick the scheme whose background you want to base colors on.\n")
            base_scheme = _pick_scheme_via_browser("Base scheme")
            if base_scheme:
                bg = hex_to_srgb(base_scheme["bg"])
                fg = hex_to_srgb(base_scheme["fg"])
                base_overrides = {
                    "fg":    base_scheme["fg"],
                    "selbg": base_scheme["selbg"],
                    "selfg": base_scheme["selfg"],
                }
                print(
                    f"  Base: bg={base_scheme['bg']}  fg={base_scheme['fg']}\n"
                )
            else:
                print("  Cancelled — using current terminal colors.\n")

    # -----------------------------------------------------------------------
    # Step 1: Derive and show directions A–D
    # -----------------------------------------------------------------------
    directions = derive_palette(bg)

    print("\n  Derived palette directions:\n")
    print(preview_all_directions(directions, fg=fg))
    print()
    print("  [E] Load custom schemes (waiting / active / blocked separately)\n")
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
        return None, None, None, "custom", {"waiting": w, "active": a, "blocked": b}, None

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

    return waiting, active, blocked, label, None, base_overrides
