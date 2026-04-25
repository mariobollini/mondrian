"""
Phase-by-phase interactive color picker for mondrian configure.

Flow per state: hue grid → closest matching schemes → confirm.
"""

from .colors import srgb_to_hsl, hsl_to_srgb, srgb_to_hex, hex_to_srgb, derive_state_colors

RESET = "\033[0m"
BOLD  = "\033[1m"

# (label, hue fraction 0–1 or None for neutral, single-key shortcut)
HUES = [
    ("Red",    0.000, "1"),
    ("Orange", 0.083, "2"),
    ("Yellow", 0.167, "3"),
    ("Green",  0.333, "4"),
    ("Teal",   0.500, "5"),
    ("Blue",   0.611, "6"),
    ("Violet", 0.750, "7"),
    ("Pink",   0.889, "8"),
    ("Gray",   None,  "9"),
]

_VALID_KEYS = {h[2] for h in HUES} | {"h", ""}


# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

def _ansi_bg(hex_color: str) -> str:
    r, g, b = (round(v * 255) for v in hex_to_srgb(hex_color))
    return f"\033[48;2;{r};{g};{b}m"

def _ansi_fg(hex_color: str) -> str:
    r, g, b = (round(v * 255) for v in hex_to_srgb(hex_color))
    return f"\033[38;2;{r};{g};{b}m"

def _swatch(hex_color: str, width: int = 5) -> str:
    return f"{_ansi_bg(hex_color)}{' ' * width}{RESET}"

def text_swatches(colors: dict) -> str:
    """Aa Bb Cc swatches — normal fg, bold, and selected text on each bg."""
    BG  = _ansi_bg(colors["bg"])
    FG  = _ansi_fg(colors["fg"])
    BD  = _ansi_fg(colors["bold"])
    SBG = _ansi_bg(colors["selbg"])
    SFG = _ansi_fg(colors["selfg"])
    return (
        f"{BG}{FG} Aa {RESET}"
        f"{BG}{BOLD}{BD} Bb {RESET}"
        f"{SBG}{SFG} Cc {RESET}"
    )


# ---------------------------------------------------------------------------
# Hue utilities
# ---------------------------------------------------------------------------

def _hue_display_hex(hue_frac, dark_mode: bool) -> str:
    """Mid-tone color for the swatch in the picker grid."""
    l = 0.38 if dark_mode else 0.62
    if hue_frac is None:
        return srgb_to_hex(*hsl_to_srgb(0.0, 0.0, l))
    return srgb_to_hex(*hsl_to_srgb(hue_frac, 0.65, l))

def _hue_base_hex(hue_frac, dark_mode: bool) -> str:
    """A reasonable terminal bg for this hue (used for 'just use this color')."""
    if hue_frac is None:
        l = 0.22 if dark_mode else 0.78
        return srgb_to_hex(*hsl_to_srgb(0.0, 0.0, l))
    l = 0.20 if dark_mode else 0.80
    return srgb_to_hex(*hsl_to_srgb(hue_frac, 0.45, l))


# ---------------------------------------------------------------------------
# Color distance
# ---------------------------------------------------------------------------

def bg_distance(hex1: str, hex2: str) -> float:
    """
    Perceptual distance between two background colors.
    Saturated colors match by hue; achromatic colors match by lightness.
    A colored+gray pair always scores worse than two same-hue colored pairs.
    """
    h1, s1, l1 = srgb_to_hsl(*hex_to_srgb(hex1))
    h2, s2, l2 = srgb_to_hsl(*hex_to_srgb(hex2))

    hd = abs(h1 - h2) % 1.0
    hd = min(hd, 1.0 - hd) * 2       # circular, normalized 0→1
    ld = abs(l1 - l2)

    # Gray (S < 0.15) and colorful colors are different "types".
    # A large fixed penalty ensures grays never appear in a colored search.
    type_mismatch = 2.5 if (s1 > 0.15) != (s2 > 0.15) else 0.0

    # Hue contribution scales with the minimum saturation so that near-grays
    # don't get false credit for sharing hue=0 with red.
    return hd * min(s1, s2) * 3.0 + ld + type_mismatch


def closest_schemes(target_hex: str, schemes: list, n: int = 6) -> list:
    """
    Return [(name, entry, colors), ...] sorted by bg proximity to target_hex.
    Loads all scheme colors eagerly (498 small XML files ≈ < 1 s).
    """
    from .colors import load_itermcolors
    print("  Searching…", end="\r", flush=True)
    scored = []
    for name, entry in schemes:
        try:
            colors = entry if isinstance(entry, dict) else load_itermcolors(entry)
            if colors:
                scored.append((bg_distance(target_hex, colors["bg"]), name, entry, colors))
        except Exception:
            pass
    scored.sort(key=lambda x: x[0])
    print("            ", end="\r", flush=True)
    return [(name, entry, colors) for _, name, entry, colors in scored[:n]]


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_hue_grid(dark_mode: bool = True) -> None:
    """Two rows of 4 + 5 hue swatches with key labels."""
    rows = [HUES[:4], HUES[4:]]
    for row in rows:
        sw_line  = "  "
        lbl_line = "  "
        for label, hf, key in row:
            color = _hue_display_hex(hf, dark_mode)
            sw_line  += f"[{key}] {_swatch(color, 5)}  "
            lbl_line += f"    {label:<11}"
        print(sw_line)
        print(lbl_line)
    print()
    print("  [h] Custom hex     [Enter] Auto-derive")
    print()


def print_review(
    waiting_colors: dict,
    active_colors:  dict,
    blocked_colors: dict,
    transparency:   dict,
) -> None:
    print("\n  ── Review ────────────────────────────────────────────────────────")
    print()
    for label, colors in [
        ("Normal     ", waiting_colors),
        ("Processing ", active_colors),
        ("Blocked    ", blocked_colors),
    ]:
        print(f"  {label}  {text_swatches(colors)}  {colors['bg']}")
    print()
    if transparency:
        wa = transparency.get("waiting", 0)
        aa = transparency.get("active",  0)
        print(f"  Transparency  {wa:.0%} at rest  →  {aa:.0%} while processing")
    else:
        print(f"  Transparency  off")
    print()


def print_review_and_confirm(
    waiting_colors: dict,
    active_colors:  dict,
    blocked_colors: dict,
    transparency:   dict,
) -> bool:
    print_review(waiting_colors, active_colors, blocked_colors, transparency)
    try:
        raw = input("  Apply? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return raw != "n"


# ---------------------------------------------------------------------------
# Interactive picker
# ---------------------------------------------------------------------------

def pick_state_color(
    phase_name:     str,
    schemes:        list,
    favorites:      set,
    waiting_colors: dict,
    dark_mode:      bool,
    hint:           str = "",
) -> "dict | None":
    """
    Hue grid → closest schemes → pick one (or auto-derive).
    Returns a {bg, fg, bold, selbg, selfg} hex dict, or None for auto-derive.
    """
    from .colors import load_itermcolors
    from .browse import run_browser

    while True:
        print_hue_grid(dark_mode)
        suffix = f" (suggested: {hint})" if hint else ""
        try:
            raw = input(f"  Hue{suffix}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if raw not in _VALID_KEYS:
            print(f"  Unknown choice — pick a number 1–9, h, or Enter.\n")
            continue

        if raw == "":
            return None                     # auto-derive

        if raw == "h":
            try:
                hex_input = input("  Enter hex (e.g. 3E5D88): ").strip().lstrip("#")
            except (EOFError, KeyboardInterrupt):
                continue
            if len(hex_input) != 6:
                print("  Expected 6 hex digits.\n")
                continue
            try:
                int(hex_input, 16)
            except ValueError:
                print("  Invalid hex.\n")
                continue
            target_hex   = f"#{hex_input.upper()}"
            target_label = target_hex
        else:
            label, hf, _ = next(h for h in HUES if h[2] == raw)
            target_hex   = _hue_base_hex(hf, dark_mode)
            target_label = label

        # Show matching schemes
        matches = closest_schemes(target_hex, schemes, n=6)
        if not matches:
            print(f"\n  No schemes in library. Run: mondrian fetch --all\n")
            return None

        print(f"\n  Closest to {target_label}  ({target_hex}):\n")
        for i, (name, _, colors) in enumerate(matches, 1):
            star = "★ " if name in favorites else "  "
            print(f"  {i}  {text_swatches(colors)}  {star}{name:<28}  {colors['bg']}")

        print()
        print(f"  j  {_swatch(target_hex, 6)}  Just use {target_hex}  (auto-derive text)")
        print(f"  m  Browse all {len(schemes)} schemes")
        print(f"  b  ← Back to hue picker")
        print()

        try:
            choice = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if choice == "b":
            continue

        if choice == "j":
            return derive_state_colors(
                hex_to_srgb(target_hex),
                hex_to_srgb(waiting_colors["fg"]),
                hex_to_srgb(waiting_colors["selbg"]),
            )

        if choice == "m":
            picked = run_browser(
                schemes, favorites, load_itermcolors,
                select_mode=True, prompt=f"Select: {phase_name}",
            )
            if picked:
                return picked
            continue

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(matches):
                return matches[idx][2]
        except ValueError:
            pass

        print("  Invalid choice — try again.\n")
