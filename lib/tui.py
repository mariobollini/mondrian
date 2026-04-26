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

RESET = "\033[0m"
BOLD  = "\033[1m"
HIDE  = "\033[?25l"
SHOW  = "\033[?25h"
DIM   = "\033[2m"


def _bg(hex_color: str) -> str:
    from .colors import hex_to_srgb
    r, g, b = (round(v * 255) for v in hex_to_srgb(hex_color))
    return f"\033[48;2;{r};{g};{b}m"


def _fg(hex_color: str) -> str:
    from .colors import hex_to_srgb
    r, g, b = (round(v * 255) for v in hex_to_srgb(hex_color))
    return f"\033[38;2;{r};{g};{b}m"


def swatches(colors: dict) -> str:
    """Aa Bb Cc text swatches — 12 visible characters wide."""
    BG  = _bg(colors["bg"])
    FG  = _fg(colors["fg"])
    BD  = _fg(colors["bold"])
    SBG = _bg(colors["selbg"])
    SFG = _fg(colors["selfg"])
    return (
        f"{BG}{FG} Aa {RESET}"
        f"{BG}{BOLD}{BD} Bb {RESET}"
        f"{SBG}{SFG} Cc {RESET}"
    )


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
    sw_vis    = 12              # " Aa " × 3 = 12 visible chars
    # swatch row content: "  " + 12 + "  " + 7 = 23 visible chars minimum
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
