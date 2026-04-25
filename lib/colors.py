"""
Color math: sRGB ↔ HSL, palette derivation, terminal preview.
All sRGB values are floats in [0, 1].
"""

import math
import os


# ---------------------------------------------------------------------------
# sRGB ↔ HSL
# ---------------------------------------------------------------------------

def srgb_to_hsl(r: float, g: float, b: float) -> tuple[float, float, float]:
    mx = max(r, g, b)
    mn = min(r, g, b)
    l = (mx + mn) / 2.0
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        h = (g - b) / d + (6 if g < b else 0)
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return (h / 6.0) % 1.0, s, l


def hsl_to_srgb(h: float, s: float, l: float) -> tuple[float, float, float]:
    if s == 0:
        return l, l, l
    def hue2rgb(p, q, t):
        t = t % 1.0
        if t < 1/6: return p + (q - p) * 6 * t
        if t < 1/2: return q
        if t < 2/3: return p + (q - p) * (2/3 - t) * 6
        return p
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    return hue2rgb(p, q, h + 1/3), hue2rgb(p, q, h), hue2rgb(p, q, h - 1/3)


def clamp(v: float, lo=0.0, hi=1.0) -> float:
    return max(lo, min(hi, v))


def srgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        round(clamp(r) * 255),
        round(clamp(g) * 255),
        round(clamp(b) * 255),
    )


def hex_to_srgb(hex_str: str) -> tuple[float, float, float]:
    h = hex_str.lstrip("#")
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )


# ---------------------------------------------------------------------------
# Palette derivation
# ---------------------------------------------------------------------------

def derive_palette(bg: tuple[float, float, float]) -> dict:
    """
    Given a baseline background color, return three palette directions.

    Each direction is a dict with keys: waiting, active, blocked
    (each value is an (r, g, b) float tuple).
    """
    r, g, b = bg
    h, s, l = srgb_to_hsl(r, g, b)

    waiting = bg  # always the user's own color

    dark = l < 0.5

    if dark:
        # Shift active/blocked lighter so they stand out against a dark bg.
        # Use larger deltas than light-mode because we're climbing out of near-zero.
        active_a  = hsl_to_srgb(0.597, max(s, 0.12), clamp(l + 0.12))
        blocked_a = hsl_to_srgb(0.103, 0.60,          clamp(l + 0.09))

        active_b  = hsl_to_srgb(0.597, max(s, 0.18), clamp(l + 0.19))
        blocked_b = hsl_to_srgb(0.02,  0.55,          clamp(l + 0.12))

        active_c  = hsl_to_srgb(0.597, max(s, 0.08), clamp(l + 0.07))
        blocked_c = hsl_to_srgb(0.75,  0.35,          clamp(l + 0.07))
    else:
        # Shift active/blocked slightly darker/different from a light bg.
        active_a  = hsl_to_srgb(0.597, max(s, 0.10), clamp(l - 0.07))
        blocked_a = hsl_to_srgb(0.103, 0.75,          clamp(l - 0.04))

        active_b  = hsl_to_srgb(0.597, max(s, 0.15), clamp(l - 0.12))
        blocked_b = hsl_to_srgb(0.02,  0.70,          clamp(l - 0.06))

        active_c  = hsl_to_srgb(0.597, max(s, 0.06), clamp(l - 0.04))
        blocked_c = hsl_to_srgb(0.75,  0.45,          clamp(l - 0.06))

    return {
        "A": {"waiting": waiting, "active": active_a, "blocked": blocked_a, "label": "cool-blue + amber (default)"},
        "B": {"waiting": waiting, "active": active_b, "blocked": blocked_b, "label": "cool-blue + rose (contrast)"},
        "C": {"waiting": waiting, "active": active_c, "blocked": blocked_c, "label": "subtle + lavender (soft)"},
        "D": {"waiting": waiting, "active": waiting,  "blocked": blocked_b, "label": "transparency only (opacity is the only signal — requires fade enabled)"},
    }


# ---------------------------------------------------------------------------
# State color derivation
# ---------------------------------------------------------------------------

def derive_state_colors(bg: tuple, fg_base: tuple, selbg_base: tuple) -> dict:
    """
    Derive a harmonious full color set for a terminal state.
    Returns hex strings for bg, fg, bold, selbg, selfg.

    Strategy for light backgrounds:
    - fg/bold: dark, hue-tinted to match the bg hue family (no white bold)
    - selbg: same hue, richly saturated, moderately dark (crisp selection)
    - selfg: near-white with a subtle hue tint
    """
    h, s, l = srgb_to_hsl(*bg)

    if l >= 0.5:  # light background
        # fg: dark, tinted with the bg hue so it feels "of a piece" with the bg
        fg_s = clamp(max(s, 0.08) * 2.0 + 0.15, 0.0, 0.80)
        fg = hsl_to_srgb(h, fg_s, 0.10)

        # selbg: same hue, richly saturated, dark — pops clearly against the light bg
        sb_s = clamp(max(s, 0.10) * 2.0 + 0.50, 0.0, 0.95)
        selbg = hsl_to_srgb(h, sb_s, 0.38)

        # selfg: near-white with a whisper of the hue
        selfg = hsl_to_srgb(h, 0.06, 0.96)

    else:  # dark background
        # fg: light, gently tinted
        fg_s = clamp(max(s, 0.08) * 1.5 + 0.05, 0.0, 0.70)
        fg = hsl_to_srgb(h, fg_s, 0.88)

        # selbg: same hue, medium saturation, medium-light
        sb_s = clamp(max(s, 0.10) * 1.5 + 0.30, 0.0, 0.80)
        selbg = hsl_to_srgb(h, sb_s, 0.62)

        # selfg: near-dark
        selfg = hsl_to_srgb(h, 0.05, 0.08)

    fg_hex = srgb_to_hex(*fg)
    return {
        "bg":    srgb_to_hex(*bg),
        "fg":    fg_hex,
        "bold":  fg_hex,   # bold = fg so iTerm2 won't render bold as bright/white
        "selbg": srgb_to_hex(*selbg),
        "selfg": srgb_to_hex(*selfg),
    }


# ---------------------------------------------------------------------------
# Terminal preview (ANSI truecolor)
# ---------------------------------------------------------------------------

def _ansi_bg(r: float, g: float, b: float) -> str:
    ri, gi, bi = round(r * 255), round(g * 255), round(b * 255)
    return f"\033[48;2;{ri};{gi};{bi}m"

def _ansi_fg(r: float, g: float, b: float) -> str:
    ri, gi, bi = round(r * 255), round(g * 255), round(b * 255)
    return f"\033[38;2;{ri};{gi};{bi}m"

RESET = "\033[0m"

def preview_palette(
    label: str,
    waiting: tuple,
    active: tuple,
    blocked: tuple,
    fg: tuple = (0.063, 0.063, 0.063),
) -> str:
    def swatch(name: str, bg: tuple) -> str:
        bg_code = _ansi_bg(*bg)
        fg_code = _ansi_fg(*fg)
        hex_val = srgb_to_hex(*bg)
        return f"  {bg_code}{fg_code}  {name:<9}{hex_val}  {RESET}"

    lines = [
        f"\n  {label}",
        swatch("Waiting", waiting),
        swatch("Active", active),
        swatch("Blocked", blocked),
    ]
    return "\n".join(lines)


def preview_all_directions(directions: dict, fg: tuple = (0.063, 0.063, 0.063)) -> str:
    parts = []
    for key, d in directions.items():
        parts.append(preview_palette(
            f"[{key}] {d['label']}",
            d["waiting"], d["active"], d["blocked"],
            fg=fg,
        ))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# .itermcolors loading
# ---------------------------------------------------------------------------

def load_itermcolors(path: str) -> dict:
    """
    Parse a .itermcolors plist file.
    Returns {bg, fg, bold, selbg, selfg} as hex strings — same shape as
    derive_state_colors(), so hooks consume it without changes.
    """
    import plistlib

    with open(path, "rb") as f:
        data = plistlib.load(f)

    def key_to_hex(key: str, fallback: tuple) -> str:
        c = data.get(key, {})
        r = c.get("Red Component",   fallback[0])
        g = c.get("Green Component", fallback[1])
        b = c.get("Blue Component",  fallback[2])
        return srgb_to_hex(r, g, b)

    fg_hex   = key_to_hex("Foreground Color", (0.063, 0.063, 0.063))
    bold_hex = key_to_hex("Bold Color", hex_to_srgb(fg_hex)) if "Bold Color" in data else fg_hex

    return {
        "bg":    key_to_hex("Background Color",   (0.98, 0.98, 0.98)),
        "fg":    fg_hex,
        "bold":  bold_hex,
        "selbg": key_to_hex("Selection Color",     (0.70, 0.84, 1.00)),
        "selfg": key_to_hex("Selected Text Color", (0.00, 0.00, 0.00)),
    }


def render_scheme_row(name: str, colors: dict, name_width: int = 30) -> str:
    """Single-line display: left-padded name + five color swatches + bg hex."""
    def swatch(hex_val: str) -> str:
        return f"{_ansi_bg(*hex_to_srgb(hex_val))}  {RESET}"

    swatches = "".join(swatch(colors[k]) for k in ("bg", "fg", "bold", "selbg", "selfg"))
    return f"  {name:<{name_width}} {swatches}  {colors['bg']}"


def scan_itermcolors(dirs: list[str]) -> list[tuple[str, str]]:
    """
    Scan directories recursively for .itermcolors files.
    Returns sorted [(name, path)], deduped by stem (first occurrence wins).
    """
    from pathlib import Path

    seen: dict[str, str] = {}
    for d in dirs:
        p = Path(d).expanduser()
        if not p.is_dir():
            continue
        for f in sorted(p.rglob("*.itermcolors")):
            if f.stem not in seen:
                seen[f.stem] = str(f)
    return sorted(seen.items(), key=lambda x: x[0].lower())
