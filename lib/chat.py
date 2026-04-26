"""
Phase-by-phase interactive configure flow.
"""

import sys
from .colors import srgb_to_hex, hex_to_srgb, srgb_to_hsl, derive_state_colors, derive_palette
from .fetch import list_local_schemes, load_favorites


# ---------------------------------------------------------------------------
# Scheme aggregation
# ---------------------------------------------------------------------------

def _get_all_schemes() -> tuple[list, set]:
    """
    Return (schemes, favorites).
    schemes = [(name, path_or_colors_dict), ...], favorites-first then alpha.
    Sources: ~/.mondrian/schemes/ + iTerm2 Custom Color Presets.
    """
    from .iterm import list_color_presets

    favorites    = load_favorites()
    local        = list_local_schemes()               # [(name, path_str)]
    presets      = list_color_presets()               # [(name, colors_dict)]
    local_names  = {n for n, _ in local}
    combined     = local + [(n, d) for n, d in presets if n not in local_names]

    def sort_key(item):
        return (0 if item[0] in favorites else 1, item[0].lower())

    return sorted(combined, key=sort_key), favorites


# ---------------------------------------------------------------------------
# Transparency prompt (moved here from mondrian.py)
# ---------------------------------------------------------------------------

def _pick_transparency(query_fn, required: bool = False) -> dict:
    """Ask whether to enable transparency fading. Returns config dict or {}."""
    print()
    if required:
        print("  Processing and normal colors are the same — transparency is required for a visible signal.")
    else:
        try:
            raw = input("  Add transparency fade (window fades while Claude is working)? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return {}
        if raw != "y":
            return {}

    current = query_fn()
    if current is None:
        print("  (Could not read current transparency via AppleScript — defaulting to 0)")
        current = 0.0

    suggested = round(min(current + 0.35, 0.85), 2)
    print(f"  Current transparency : {current:.0%}  (0% = opaque, 100% = clear)")
    try:
        raw = input(f"  Processing transparency [{suggested:.0%}]: ").strip().rstrip("%")
    except (EOFError, KeyboardInterrupt):
        return {}

    if raw:
        try:
            v = float(raw)
            active_alpha = v / 100 if v > 1 else v
        except ValueError:
            print("  Invalid value, skipping transparency.")
            return {}
    else:
        active_alpha = suggested

    active_alpha = max(0.0, min(1.0, active_alpha))
    print(f"  Normal: {current:.0%} → Processing: {active_alpha:.0%}")
    return {"waiting": round(current, 3), "active": round(active_alpha, 3)}


# ---------------------------------------------------------------------------
# Main configure flow
# ---------------------------------------------------------------------------

def configure_phases(profile: dict) -> "tuple | None":
    """
    Phase-by-phase interactive configuration.
    Returns (waiting_colors, active_colors, blocked_colors, transparency_config)
    or None if the user cancels at the review step.
    All *_colors are {bg, fg, bold, selbg, selfg} hex dicts.
    """
    from .picker import pick_state_color, text_swatches, print_review_and_confirm
    from .iterm import query_terminal_transparency

    dark_mode = srgb_to_hsl(*profile["bg"])[2] < 0.5
    schemes, favorites = _get_all_schemes()

    def section(title: str, desc: str) -> None:
        pad = max(1, 58 - len(title))
        print(f"\n  ── {title} {'─' * pad}")
        print(f"  {desc}\n")

    def auto_active(wc: dict) -> dict:
        pal = derive_palette(hex_to_srgb(wc["bg"]))
        return derive_state_colors(
            pal["B"]["active"],
            hex_to_srgb(wc["fg"]),
            hex_to_srgb(wc["selbg"]),
        )

    def auto_blocked(wc: dict) -> dict:
        pal = derive_palette(hex_to_srgb(wc["bg"]))
        return derive_state_colors(
            pal["B"]["blocked"],
            hex_to_srgb(wc["fg"]),
            hex_to_srgb(wc["selbg"]),
        )

    # ── Phase 1: Normal / Waiting ────────────────────────────────────────
    section("Normal", "Your everyday terminal. Mondrian won't change this color.")

    waiting_colors: dict = {
        "bg":    srgb_to_hex(*profile["bg"]),
        "fg":    srgb_to_hex(*profile["fg"]),
        "bold":  srgb_to_hex(*profile["fg"]),
        "selbg": srgb_to_hex(*profile["selbg"]),
        "selfg": srgb_to_hex(*profile["selfg"]),
    }

    print(f"  {text_swatches(waiting_colors)}  {waiting_colors['bg']}\n")

    try:
        raw = input("  Customize? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        raw = ""

    if raw == "y":
        picked = pick_state_color(
            "Normal", schemes, favorites, waiting_colors, dark_mode,
        )
        if picked:
            waiting_colors = picked

    # ── Phase 2: Processing / Active ────────────────────────────────────
    section(
        "Processing",
        "Fires the moment you press Enter. Stays on while Claude is thinking.",
    )

    active_colors = pick_state_color(
        "Processing", schemes, favorites, waiting_colors, dark_mode,
        hint="blue [6]",
    )
    if active_colors is None:
        active_colors = auto_active(waiting_colors)
        print(f"  Auto-derived  →  {active_colors['bg']}\n")

    # ── Phase 3: Blocked ─────────────────────────────────────────────────
    section(
        "Blocked",
        "Fires when Claude needs your approval to use a tool or read a file.",
    )

    try:
        raw = input("  Enable blocked indicator? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        raw = ""
    blocked_enabled = raw != "n"

    if blocked_enabled:
        blocked_colors = pick_state_color(
            "Blocked", schemes, favorites, waiting_colors, dark_mode,
            hint="red [1]",
        )
        if blocked_colors is None:
            blocked_colors = auto_blocked(waiting_colors)
            print(f"  Auto-derived  →  {blocked_colors['bg']}\n")
    else:
        blocked_colors = dict(waiting_colors)
        print(f"  Blocked indicator disabled.\n")

    # ── Phase 4: Transparency ────────────────────────────────────────────
    transparency_required = waiting_colors["bg"] == active_colors["bg"]
    transparency_config   = _pick_transparency(
        query_terminal_transparency, required=transparency_required,
    )

    # ── Review + confirm ─────────────────────────────────────────────────
    if not print_review_and_confirm(
        waiting_colors, active_colors, blocked_colors, transparency_config
    ):
        print("  Cancelled.\n")
        return None

    return waiting_colors, active_colors, blocked_colors, transparency_config, blocked_enabled
