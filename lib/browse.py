"""
Full-screen interactive scheme browser.

Navigation: ↑↓ or j/k — Enter/Space = toggle bookmark — q = quit
"""

import os
import select
import sys
import termios
import tty

_HIDE   = "\033[?25l"
_SHOW   = "\033[?25h"
_HOME   = "\033[H"
_CLR    = "\033[2J"
_EOL    = "\033[K"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"


# ---------------------------------------------------------------------------
# Keypress reader
# ---------------------------------------------------------------------------

def _getch() -> str:
    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1).decode("latin-1")
        if ch == "\x1b":
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch += os.read(fd, 4).decode("latin-1", errors="ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


# ---------------------------------------------------------------------------
# Row rendering (self-contained so the highlight doesn't fight the swatches)
# ---------------------------------------------------------------------------

def _swatch(hex_val: str) -> str:
    from .colors import hex_to_srgb, srgb_to_hsl, hsl_to_srgb, clamp
    r, g, b = hex_to_srgb(hex_val)
    h, s, l = srgb_to_hsl(r, g, b)
    bl      = clamp(l + (0.25 if l < 0.5 else -0.25))
    br, bg_, bb = hsl_to_srgb(h, s, bl)
    border  = f"\033[48;2;{round(br*255)};{round(bg_*255)};{round(bb*255)}m"
    fill    = f"\033[48;2;{round(r*255)};{round(g*255)};{round(b*255)}m"
    return f"{border} {fill}    {border} {_RESET}"


def _row(idx: int, name: str, colors: dict | None, bookmarked: bool, selected: bool) -> str:
    mark   = "★ " if bookmarked else "  "
    num    = f"{idx + 1:3d}"
    arrow  = "►" if selected else " "

    if colors is None:
        body = f"{mark}{name}  (unreadable)"
    else:
        name_str = f"{mark}{name:<32}"
        if selected:
            name_str = f"{_BOLD}{name_str}{_RESET}"
        swatches = " ".join(_swatch(colors[k]) for k in ("bg", "fg", "bold", "selbg", "selfg"))
        body = f"{name_str} {swatches}  {colors['bg']}"

    return f"  {arrow} {num}  {body}{_EOL}"


# ---------------------------------------------------------------------------
# Browser loop
# ---------------------------------------------------------------------------

def run_browser(schemes: list, favorites: set, load_fn, live_filter: bool = False) -> set:
    """
    Run the full-screen browser. Returns the (possibly updated) favorites set.

    schemes : [(name, path), ...]
    load_fn : callable(path) -> {bg, fg, bold, selbg, selfg} hex dict
    """
    if not schemes:
        return favorites

    schemes = list(schemes)  # work with a local copy so live_filter splices are safe
    cache:  dict = {}
    cursor: int  = 0
    vtop:   int  = 0

    def colors_for(i: int):
        if i not in cache:
            try:
                cache[i] = load_fn(schemes[i][1])
            except Exception:
                cache[i] = None
        return cache[i]

    def ui_h() -> int:
        return max(1, os.get_terminal_size().lines - 6)  # 4 header + 2 footer

    def scroll():
        nonlocal vtop
        h = ui_h()
        if cursor < vtop:
            vtop = cursor
        elif cursor >= vtop + h:
            vtop = cursor - h + 1
        vtop = max(0, min(vtop, max(0, len(schemes) - h)))

    def draw():
        scroll()
        h   = ui_h()
        end = min(vtop + h, len(schemes))
        fc  = sum(1 for n, _ in schemes if n in favorites)

        buf = [_HOME]
        buf.append(f"  {len(schemes)} schemes · {fc} bookmarked{_EOL}")
        buf.append(f"  Swatches: bg · fg · bold · selbg · selfg{_EOL}")
        buf.append(f"  ↑↓ / jk navigate   Enter = bookmark   q = done{_EOL}")
        buf.append(_EOL)

        for i in range(vtop, end):
            buf.append(_row(i, schemes[i][0], colors_for(i),
                            bookmarked=(schemes[i][0] in favorites),
                            selected=(i == cursor)))

        for _ in range(h - (end - vtop)):      # blank remaining rows
            buf.append(_EOL)

        buf.append(_EOL)
        buf.append(f"  {cursor + 1} / {len(schemes)}{_EOL}")

        sys.stdout.write("\n".join(buf))
        sys.stdout.flush()

    sys.stdout.write(_HIDE + _CLR)
    sys.stdout.flush()

    try:
        draw()

        while True:
            key = _getch()

            if key in ("q", "Q", "\x03"):               # quit
                break
            elif key in ("\r", "\n", " "):              # toggle bookmark
                name = schemes[cursor][0]
                if name in favorites:
                    favorites.discard(name)
                    if live_filter:
                        schemes.pop(cursor)
                        # invalidate any cached index above the removed slot
                        cache = {i: v for i, v in cache.items() if i < cursor}
                        if not schemes:
                            break
                        cursor = min(cursor, len(schemes) - 1)
                else:
                    favorites.add(name)
                draw()
            elif key in ("\x1b[A", "\x1bOA", "k"):     # up
                cursor = max(0, cursor - 1)
                draw()
            elif key in ("\x1b[B", "\x1bOB", "j"):     # down
                cursor = min(len(schemes) - 1, cursor + 1)
                draw()
            elif key in ("\x1b[5~",):                   # page up
                cursor = max(0, cursor - ui_h())
                draw()
            elif key in ("\x1b[6~",):                   # page down
                cursor = min(len(schemes) - 1, cursor + ui_h())
                draw()
            elif key in ("g", "\x1b[H", "\x1b[1~"):    # first
                cursor = 0
                draw()
            elif key in ("G", "\x1b[F", "\x1b[4~"):    # last
                cursor = len(schemes) - 1
                draw()

    finally:
        sys.stdout.write(_SHOW + _CLR + _HOME)
        sys.stdout.flush()

    return favorites
