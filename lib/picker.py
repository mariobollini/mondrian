"""
Phase-by-phase interactive color picker for mondrian configure.

Flow per state:
  canvas preview  →  hue grid  →  scheme picker (↑↓ live canvas preview)  →  done
"""

import sys

from .colors import srgb_to_hsl, hsl_to_srgb, srgb_to_hex, hex_to_srgb, derive_state_colors
from .tui    import (
    _bg as _ansi_bg, _fg as _ansi_fg,
    swatches as text_swatches,
    canvas_lines, canvas_height,
    RESET, BOLD, DIM, HIDE, SHOW,
)

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
# Swatch helper (small inline swatches for the hue grid)
# ---------------------------------------------------------------------------

def _swatch(hex_color: str, width: int = 5, dark_mode: bool = True) -> str:
    # █ full-block glyph: foreground-drawn so unaffected by bg color overrides
    bdr_fg = "\033[38;2;190;195;210m" if dark_mode else "\033[38;2;70;75;85m"
    bdr = f"{bdr_fg}█{RESET}"
    return f"{bdr}{_ansi_bg(hex_color)}{' ' * width}{RESET}{bdr}"


# ---------------------------------------------------------------------------
# Hue utilities
# ---------------------------------------------------------------------------

def _hue_display_hex(hue_frac, dark_mode: bool) -> str:
    """Mid-tone color for the swatch in the hue picker grid."""
    l = 0.38 if dark_mode else 0.62
    if hue_frac is None:
        return srgb_to_hex(*hsl_to_srgb(0.0, 0.0, l))
    return srgb_to_hex(*hsl_to_srgb(hue_frac, 0.65, l))

def _hue_base_hex(hue_frac, dark_mode: bool) -> str:
    """A reasonable terminal bg for this hue (seed for scheme search)."""
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

    # Gray (S < 0.15) vs colorful → large penalty so grays never pollute colored searches
    type_mismatch = 2.5 if (s1 > 0.15) != (s2 > 0.15) else 0.0

    return hd * min(s1, s2) * 3.0 + ld + type_mismatch


def closest_schemes(target_hex: str, schemes: list, n: int = 6) -> list:
    """Return [(name, entry, colors), ...] sorted by bg proximity to target_hex."""
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
# Hue grid
# ---------------------------------------------------------------------------

def print_hue_grid(dark_mode: bool = True) -> None:
    """Two rows of 4 hue swatches + Gray row, labels inline."""
    for row in [HUES[:4], HUES[4:8]]:
        line = "  "
        for label, hf, key in row:
            color = _hue_display_hex(hf, dark_mode)
            line += f"{BOLD}[{key}]{RESET} {_swatch(color, 4, dark_mode)} {label:<8}"
        print(line)

    label, hf, key = HUES[8]
    color = _hue_display_hex(hf, dark_mode)
    print(
        f"  {BOLD}[{key}]{RESET} {_swatch(color, 4, dark_mode)} {label:<8}"
        f"  {DIM}[h]{RESET} Custom hex"
        f"     {DIM}[Enter]{RESET} Auto-derive"
    )
    print()


# ---------------------------------------------------------------------------
# Canvas helpers used within this module
# ---------------------------------------------------------------------------

def _draw_canvas_static(waiting_colors: dict, phase_slot: str,
                         other_colors: "dict | None") -> None:
    """Print the canvas above the hue grid (pending slot shown as placeholder)."""
    if phase_slot == "active":
        lines = canvas_lines(waiting_colors, None, other_colors)
    else:
        lines = canvas_lines(waiting_colors, other_colors, None)
    print()
    for line in lines:
        print(line)
    print()


# ---------------------------------------------------------------------------
# Interactive scheme picker with live Mondrian canvas
# ---------------------------------------------------------------------------

def _run_scheme_picker(
    matches:       list,
    target_hex:    str,
    target_label:  str,
    schemes:       list,
    favorites:     set,
    waiting_colors: dict,
    phase_slot:    str,
    other_colors:  "dict | None",
) -> "dict | None | str":
    """
    Full-height interactive scheme picker.

    ► cursor navigates the list; canvas at top updates live to preview each scheme.

    Returns:
      dict   — selected colors
      'j'    — just use target_hex (auto-derive text)
      'm'    — open full browser
      'b'    — back to hue picker
      None   — cancel
    """
    from .browse import _getch

    cursor  = 0
    n_shown = 0  # lines currently on screen (for up-move redraw)

    j_colors = derive_state_colors(
        hex_to_srgb(target_hex),
        hex_to_srgb(waiting_colors["fg"]),
        hex_to_srgb(waiting_colors["selbg"]),
    )

    def _cv(preview: dict) -> list[str]:
        if phase_slot == "active":
            return canvas_lines(waiting_colors, preview, other_colors)
        return canvas_lines(waiting_colors, other_colors, preview)

    def _screen() -> list[str]:
        out = [""] + _cv(matches[cursor][2]) + [""]

        out.append(f"  Closest to {target_label}  ({target_hex}):")
        out.append("")

        for i, (name, _, colors) in enumerate(matches):
            star  = "★ " if name in favorites else "  "
            mark  = "►" if i == cursor else " "
            sw    = text_swatches(colors)
            ndisp = (f"\033[1m{name:<26}\033[m"
                     if i == cursor else f"{name:<26}")
            out.append(f"  {mark} {i+1}  {sw}  {star}{ndisp}  {colors['bg']}")

        out.append("")
        out.append(f"  {BOLD}j{RESET}  {text_swatches(j_colors)}  {DIM}Just use {target_hex}{RESET}")
        out.append(f"  {BOLD}m{RESET}  {DIM}Browse all {len(schemes)} schemes{RESET}")
        out.append(f"  {BOLD}b{RESET}  {DIM}← Back to hue picker{RESET}")
        out.append("")
        out.append(f"  {DIM}↑↓ / jk  preview  ·  Enter select  ·  1–{len(matches)}  ·  j m b  ·  q cancel{RESET}")

        return out

    def _write(lines: list[str], n_prev: int) -> int:
        if n_prev:
            sys.stdout.write(f"\033[{n_prev}A")
        for line in lines:
            sys.stdout.write(f"\033[2K{line}\n")
        sys.stdout.flush()
        return len(lines)

    sys.stdout.write(HIDE)
    n_shown = _write(_screen(), 0)

    try:
        while True:
            key = _getch()

            if key in ("\x1b[A", "\x1bOA", "k"):   # up
                if cursor > 0:
                    cursor -= 1
                    n_shown = _write(_screen(), n_shown)

            elif key in ("\x1b[B", "\x1bOB"):       # down (j reserved for "just use")
                if cursor < len(matches) - 1:
                    cursor += 1
                    n_shown = _write(_screen(), n_shown)

            elif key in ("\r", "\n"):
                return matches[cursor][2]

            elif key.isdigit():
                idx = int(key) - 1
                if 0 <= idx < len(matches):
                    return matches[idx][2]

            elif key == "j":
                return "j"
            elif key == "m":
                return "m"
            elif key == "b":
                # Clear this display area so the hue grid appears cleanly above
                sys.stdout.write(f"\033[{n_shown}A")
                for _ in range(n_shown):
                    sys.stdout.write("\033[2K\n")
                sys.stdout.write(f"\033[{n_shown}A")
                sys.stdout.flush()
                return "b"

            elif key in ("q", "\x03"):
                return None

    finally:
        sys.stdout.write(SHOW)
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

def print_review(
    waiting_colors: dict,
    active_colors:  dict,
    blocked_colors: dict,
    transparency:   dict,
) -> None:
    # Slate-blue accent (matches section header accent in chat.py)
    _ACC = "\033[38;2;99;120;192m"

    lines = canvas_lines(waiting_colors, active_colors, blocked_colors)
    print(f"\n  {_ACC}◆{RESET}  {BOLD}Review{RESET}  {DIM}{'─' * 52}{RESET}")
    print()
    for line in lines:
        print(line)
    print()
    for label, colors in [
        ("Waiting    ", waiting_colors),
        ("Processing ", active_colors),
        ("Blocked    ", blocked_colors),
    ]:
        print(f"  {DIM}{label}{RESET}  {text_swatches(colors)}  {DIM}{colors['bg']}{RESET}")
    print()
    if transparency:
        wa = transparency.get("waiting", 0)
        aa = transparency.get("active",  0)
        print(f"  {DIM}Transparency  {RESET}{wa:.0%} → {aa:.0%} while processing")
    else:
        print(f"  {DIM}Transparency  off{RESET}")
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
# Main picker entry point
# ---------------------------------------------------------------------------

def pick_state_color(
    phase_name:     str,
    schemes:        list,
    favorites:      set,
    waiting_colors: dict,
    dark_mode:      bool,
    hint:           str = "",
    phase_slot:     str = "active",
    other_colors:   "dict | None" = None,
) -> "dict | None":
    """
    Hue grid → scheme picker (with live Mondrian canvas preview).
    Returns a {bg, fg, bold, selbg, selfg} hex dict, or None for auto-derive.

    phase_slot   : "active" or "blocked" — which canvas slot this pick fills
    other_colors : already-configured colors for the other slot (shown statically)
    """
    from .colors import load_itermcolors
    from .browse import run_browser

    while True:
        _draw_canvas_static(waiting_colors, phase_slot, other_colors)
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
            return None   # auto-derive

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

        matches = closest_schemes(target_hex, schemes, n=6)
        if not matches:
            print("\n  No schemes in library. Run: mondrian fetch --all\n")
            return None

        result = _run_scheme_picker(
            matches, target_hex, target_label, schemes, favorites,
            waiting_colors, phase_slot, other_colors,
        )

        if result is None:
            return None
        elif result == "b":
            continue   # back to hue grid
        elif result == "j":
            return derive_state_colors(
                hex_to_srgb(target_hex),
                hex_to_srgb(waiting_colors["fg"]),
                hex_to_srgb(waiting_colors["selbg"]),
            )
        elif result == "m":
            picked = run_browser(
                schemes, favorites, load_itermcolors,
                select_mode=True, prompt=f"Select: {phase_name}",
            )
            if picked:
                return picked
            continue   # back to hue grid after browser exits
        else:
            return result   # colors dict
