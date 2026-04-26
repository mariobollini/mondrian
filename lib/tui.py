"""
Mondrian canvas — three state-color blocks rendered as ANSI terminal panels.

Layout (ASCII sketch):

  ██████████████████████████   ████████████████████
  █                         █  █                  █
  █  Aa Bb Cc  #15191E      █  █  Aa Bb Cc #2E34  █
  █  Waiting                █  █  Processing      █
  █                         █  ████████████████████
  █                         █
  █                         █  ████████████████████
  █                         █  █                  █
  █                         █  █  ? Blocked       █
  ██████████████████████████   ████████████████████

Waiting takes the full left column (tall).
Processing sits top-right, Blocked bottom-right.
The gap between columns is the terminal background — the "black line".
"""

import shutil

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
ITALIC = "\033[3m"
HIDE   = "\033[?25l"
SHOW   = "\033[?25h"

# Default banner colors when not yet configured (handsome dark slate defaults)
_DEFAULT_W = "#1C2026"
_DEFAULT_A = "#1D3A5C"
_DEFAULT_B = "#5C1D1D"


def _bg(hex_color: str) -> str:
    from .colors import hex_to_srgb
    r, g, b = (round(v * 255) for v in hex_to_srgb(hex_color))
    return f"\033[48;2;{r};{g};{b}m"


def _fg(hex_color: str) -> str:
    from .colors import hex_to_srgb
    r, g, b = (round(v * 255) for v in hex_to_srgb(hex_color))
    return f"\033[38;2;{r};{g};{b}m"


def swatches(colors: dict) -> str:
    """██ Aa  Bb  Cc ██ text swatches — 16 visible characters wide."""
    BG  = _bg(colors["bg"])
    FG  = _fg(colors["fg"])
    BD  = _fg(colors["bold"])
    SBG = _bg(colors["selbg"])
    SFG = _fg(colors["selfg"])
    # █ full-block glyph in fg color: foreground-drawn, unaffected by bg overrides
    bdr = f"{FG}██{RESET}"
    return (
        f"{bdr}"
        f"{BG}{FG} Aa {RESET}"
        f"{BG}{BOLD}{BD} Bb {RESET}"
        f"{SBG}{SFG} Cc {RESET}"
        f"{bdr}"
    )


def banner(
    waiting_hex:  "str | None" = None,
    active_hex:   "str | None" = None,
    blocked_hex:  "str | None" = None,
    subtitle: str = "iTerm2 colorizer for Claude Code",
    note:     str = "",
) -> None:
    """
    Tri-color Mondrian stripe + title line.
    Row 1: plain color fill.  Row 2: same color + fg-labeled state name.
    The label guarantees the Waiting stripe is visible even when its bg matches
    the terminal background.
    """
    from .colors import hex_to_srgb, srgb_to_hsl

    cols = shutil.get_terminal_size((80, 24)).columns

    w_hex = waiting_hex or _DEFAULT_W
    a_hex = active_hex  or _DEFAULT_A
    b_hex = blocked_hex or _DEFAULT_B

    margin = 2
    gap    = 2
    inner  = cols - margin * 2 - gap * 2
    w_w    = inner // 3
    a_w    = inner // 3
    b_w    = inner - w_w - a_w

    # Muted blue-gray █ border — visible on dark terminals, unaffected by bg
    B = "\033[38;2;130;135;150m"

    def _contrast(hex_color: str) -> str:
        l = srgb_to_hsl(*hex_to_srgb(hex_color))[2]
        return "\033[38;2;210;215;230m" if l < 0.5 else "\033[38;2;40;45;55m"

    # Each panel's total visual width; border chars take 1 on each side
    panels = [
        (w_hex, "Waiting",    w_w),
        (a_hex, "Processing", a_w),
        (b_hex, "Blocked",    b_w),
    ]

    def _border_row() -> str:
        parts = [f"{B}{'█' * w}{RESET}" for _, _, w in panels]
        return " " * margin + (" " * gap).join(parts)

    def _fill_row(labeled: bool) -> str:
        parts = []
        for hex_color, label, w in panels:
            cw = w - 2
            BG = _bg(hex_color)
            if labeled:
                FG  = _contrast(hex_color)
                pad = max(0, cw - len(label) - 1)
                content = f"{BG}{FG} {label}{' ' * pad}{RESET}"
            else:
                content = f"{BG}{' ' * cw}{RESET}"
            parts.append(f"{B}█{RESET}{content}{B}█{RESET}")
        return " " * margin + (" " * gap).join(parts)

    note_str = f"  {DIM}{note}{RESET}" if note else ""
    print()
    print(_border_row())
    print(_fill_row(labeled=False))
    print(_fill_row(labeled=True))
    print(_border_row())
    print(f"\n  {BOLD}mondrian{RESET}  {DIM}—  {subtitle}{RESET}{note_str}")
    print()


# Pending block styling (not yet configured)
_PND_BG = "\033[48;2;18;20;26m"
_PND_FG = "\033[38;2;52;56;76m"


def _block_lines(colors: "dict | None", width: int, height: int, label: str) -> list[str]:
    """
    Render a state block as a list of ANSI-formatted strings (no trailing newlines).
    colors=None → dim 'not yet configured' placeholder.
    width is in visual characters.
    """
    if colors is None:
        blank = _PND_BG + " " * width + RESET
        mid   = height // 2
        out   = []
        for i in range(height):
            if i == mid:
                t = f"  {label}"
                out.append(_PND_BG + _PND_FG + t + " " * max(0, width - len(t)) + RESET)
            else:
                out.append(blank)
        return out

    BG    = _bg(colors["bg"])
    FG    = _fg(colors["fg"])
    blank = BG + " " * width + RESET

    hex_str   = colors["bg"]   # 7 chars e.g. "#2E3440"
    sw_vis    = 16              # 2-bdr + " Aa " × 3 + 2-bdr = 16 visible chars
    # swatch row content: "  " + 16 + "  " + 7 = 27 visible chars minimum
    sw_trail  = max(0, width - 2 - sw_vis - 2 - len(hex_str))
    lbl_trail = max(0, width - 2 - len(label))

    sw_row  = height // 2 - 1
    lbl_row = height // 2

    out = []
    for i in range(height):
        if i == sw_row:
            out.append(
                f"{BG}{FG}  {swatches(colors)}{BG}{FG}  {hex_str}"
                + " " * sw_trail + RESET
            )
        elif i == lbl_row:
            out.append(f"{BG}{FG}  {label}" + " " * lbl_trail + RESET)
        else:
            out.append(blank)
    return out


def canvas_lines(
    waiting_colors: dict,
    active_colors:  "dict | None",
    blocked_colors: "dict | None",
) -> list[str]:
    """
    Return the Mondrian canvas as a flat list of ANSI-formatted strings.
    No surrounding blank lines — callers add those.
    """
    cols = shutil.get_terminal_size((80, 24)).columns

    # Widths: waiting ~54% of terminal, right panels get the rest
    lw = max(28, int(cols * 0.54) - 2)
    rw = max(24, cols - lw - 7)          # 7 = gap(3) + margins(2+2)
    if lw + rw + 7 > cols:
        lw = cols - rw - 7

    sh = 5           # small block height (processing, blocked)
    lh = sh * 2 + 1  # large block height (waiting) — includes the gap row

    left  = _block_lines(waiting_colors, lw, lh, "Waiting")
    top_r = _block_lines(active_colors,  rw, sh, "Processing")
    bot_r = _block_lines(blocked_colors, rw, sh, "Blocked")

    lm  = "  "   # left margin (part of the "frame")
    gap = "   "  # 3-space gap between columns (the "black line")

    out = []
    for i in range(lh):
        if i < sh:
            r = top_r[i]
        elif i == sh:
            r = ""   # gap row — right side is empty; terminal bg shows through
        else:
            r = bot_r[i - sh - 1]
        out.append(f"{lm}{left[i]}{gap}{r}")
    return out


def canvas_height() -> int:
    """Number of lines canvas_lines() returns (independent of content)."""
    return 5 * 2 + 1   # lh = sh*2 + 1
