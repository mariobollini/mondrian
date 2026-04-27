"""
Mondrian canvas — three equal-width state tiles rendered as ANSI terminal panels.

Layout (equal tiles):

  ███████████████  ████████████████  ████████████████
   Aa Bb Cc #hex    Aa Bb Cc #hex     Aa Bb Cc #hex
   Waiting           Processing        Blocked
  ███████████████  ████████████████  ████████████████

Top and bottom borders are rendered in each tile's fg color so they're always
visible regardless of whether the bg matches the terminal background.
"""

import shutil

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
ITALIC = "\033[3m"
HIDE   = "\033[?25l"
SHOW   = "\033[?25h"

# Default banner colors when not yet configured
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

    B = "\033[38;2;130;135;150m"

    def _contrast(hex_color: str) -> str:
        l = srgb_to_hsl(*hex_to_srgb(hex_color))[2]
        return "\033[38;2;210;215;230m" if l < 0.5 else "\033[38;2;40;45;55m"

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
    Render a state tile as a list of ANSI-formatted strings (no trailing newlines).
    colors=None → dim placeholder.  width in visual characters.

    Layout (height=5):
      row 0: ████ fg-colored top border
      row 1: swatches + hex  (or just swatches if tile is narrow)
      row 2: state label
      row 3: blank fill
      row 4: ████ fg-colored bottom border
    """
    if colors is None:
        blank = _PND_BG + " " * width + RESET
        bdr   = _PND_FG + "█" * width + RESET
        mid   = height // 2
        out   = []
        for i in range(height):
            if i == 0 or i == height - 1:
                out.append(bdr)
            elif i == mid:
                t = f"  ? {label}"
                out.append(_PND_BG + _PND_FG + t + " " * max(0, width - len(t)) + RESET)
            else:
                out.append(blank)
        return out

    BG    = _bg(colors["bg"])
    FG    = _fg(colors["fg"])
    bdr   = FG + "█" * width + RESET      # fg-colored top/bottom border
    blank = BG + " " * width + RESET

    hex_str   = colors["bg"]              # e.g. "#2E3440"
    sw_vis    = 16                        # visible width of swatches()
    lbl_trail = max(0, width - 2 - len(label))

    out = []
    for i in range(height):
        if i == 0 or i == height - 1:
            out.append(bdr)
        elif i == 1:
            # Swatches row: show swatches+hex if wide enough, else just swatches
            if width >= sw_vis + 2 + 2 + len(hex_str):
                sw_trail = width - 2 - sw_vis - 2 - len(hex_str)
                out.append(
                    f"{BG}{FG}  {swatches(colors)}{BG}{FG}  {hex_str}"
                    + " " * sw_trail + RESET
                )
            elif width >= sw_vis + 2:
                sw_trail = max(0, width - 2 - sw_vis)
                out.append(f"{BG}{FG}  {swatches(colors)}" + " " * sw_trail + RESET)
            else:
                out.append(blank)
        elif i == 2:
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
    Return the Mondrian canvas as three equal-width tiles side by side.
    No surrounding blank lines — callers add those.
    """
    cols = shutil.get_terminal_size((80, 24)).columns

    margin = 2
    gap    = 3
    inner  = cols - margin * 2 - gap * 2   # width for 3 tiles + 2 gaps
    w_w    = inner // 3
    a_w    = inner // 3
    b_w    = inner - w_w - a_w

    height = 5

    left  = _block_lines(waiting_colors,  w_w, height, "Waiting")
    mid   = _block_lines(active_colors,   a_w, height, "Processing")
    right = _block_lines(blocked_colors,  b_w, height, "Blocked")

    lm      = " " * margin
    gap_str = " " * gap

    return [f"{lm}{left[i]}{gap_str}{mid[i]}{gap_str}{right[i]}" for i in range(height)]


def canvas_height() -> int:
    """Number of lines canvas_lines() returns (independent of content)."""
    return 5
