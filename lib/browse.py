"""
Full-screen interactive scheme browser.

Navigation: ↑↓ or j/k — Enter/Space = toggle bookmark — q = quit
Rows are two display lines each: text swatches on line 1, bg color bar on line 2.

Extra keys:
  s / S     toggle sort (alphabetical ↔ by background hue)
  /         start name prefix jump (type to jump, Esc to cancel, / to clear)
  +         fetch a scheme by name and add to library
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
_DIM    = "\033[2m"
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
# Row rendering (2-line format)
# ---------------------------------------------------------------------------

_NAME_W = 26    # visible name column width

# Swatch: each segment 6 chars wide + ██ borders on each side = 22 visible chars
_SW_SEG = 6
_SW_VIS = 2 + _SW_SEG * 3 + 2   # = 22 visible chars


def _esc(hex_val: str, layer: str) -> str:
    """Return an ANSI SGR color code (38=fg, 48=bg) for a hex color."""
    from .colors import hex_to_srgb
    r, g, b = (round(v * 255) for v in hex_to_srgb(hex_val))
    code = 48 if layer == "bg" else 38
    return f"\033[{code};2;{r};{g};{b}m"


def _text_swatches(colors: dict) -> str:
    """
    Three wide text samples with fg-colored ██ borders.
    Total visible width: 22 chars.
    """
    BG  = _esc(colors["bg"],    "bg")
    FG  = _esc(colors["fg"],    "fg")
    BD  = _esc(colors["bold"],  "fg")
    SBG = _esc(colors["selbg"], "bg")
    SFG = _esc(colors["selfg"], "fg")

    bdr    = f"{FG}██{_RESET}"
    normal = f"{BG}{FG}  Aa  {_RESET}"
    bold   = f"{BG}{_BOLD}{BD}  Bb  {_RESET}"
    sel    = f"{SBG}{SFG}  Cc  {_RESET}"

    return f"{bdr}{normal}{bold}{sel}{bdr}"


def _contrast_fg(hex_bg: str) -> str:
    """Return a contrasting fg escape code for text on the given bg color."""
    from .colors import hex_to_srgb, srgb_to_hsl
    l = srgb_to_hsl(*hex_to_srgb(hex_bg))[2]
    return "\033[38;2;215;220;235m" if l < 0.5 else "\033[38;2;35;40;50m"


def _row(idx: int, name: str, colors: "dict | None",
         bookmarked: bool, selected: bool) -> tuple[str, str]:
    """
    Return (line1, line2) for a 2-line scheme row.

    Line 1: nav arrow + number + bookmark + name + text swatches
    Line 2: indented wide background color bar with hex
    """
    mark  = "★ " if bookmarked else "  "
    num   = f"{idx + 1:3d}"
    arrow = "►" if selected else " "

    if colors is None:
        l1 = f"  {arrow} {num}  {mark}{name}  (unreadable){_EOL}"
        l2 = f"{_EOL}"
        return l1, l2

    name_str = f"{mark}{name:<{_NAME_W}}"
    if selected:
        name_str = f"{_BOLD}{name_str}{_RESET}"

    sw = _text_swatches(colors)
    l1 = f"  {arrow} {num}  {name_str}  {sw}{_EOL}"

    # Line 2: bg color bar aligned with swatches
    # Indent: "  "(2) + arrow(1) + " "(1) + num(3) + "  "(2) + mark(2) + name(_NAME_W) + "  "(2) = 39
    indent   = 2 + 1 + 1 + 3 + 2 + 2 + _NAME_W + 2
    BG_esc   = _esc(colors["bg"], "bg")
    txt      = _contrast_fg(colors["bg"])
    bar_text = f" {colors['bg']} "
    bar_pad  = " " * max(0, _SW_VIS - len(bar_text))
    bar      = BG_esc + txt + bar_text + bar_pad + _RESET
    l2       = " " * indent + bar + _EOL

    return l1, l2


# ---------------------------------------------------------------------------
# Hue sort key
# ---------------------------------------------------------------------------

def _hue_sort_key(colors: "dict | None") -> tuple:
    """Sort: colorful schemes first by hue, then grays by lightness, unreadable last."""
    if colors is None:
        return (2, 0.0, 0.0)
    from .colors import hex_to_srgb, srgb_to_hsl
    h, s, l = srgb_to_hsl(*hex_to_srgb(colors["bg"]))
    if s < 0.12:
        return (1, l, 0.0)
    return (0, h, l)


# ---------------------------------------------------------------------------
# Browser loop
# ---------------------------------------------------------------------------

def run_browser(
    schemes: list,
    favorites: set,
    load_fn,
    live_filter: bool = False,
    select_mode: bool = False,
    prompt: str = "",
):
    """
    Run the full-screen browser.

    Bookmark mode (select_mode=False):  returns updated favorites set.
    Select mode (select_mode=True):     returns colors dict on Enter, None on q.
    """
    if not schemes:
        return None if select_mode else favorites

    schemes      = list(schemes)
    orig_schemes = list(schemes)   # saved for sort-by-name reset
    cache: dict  = {}
    cursor       = 0
    vtop         = 0
    _selected    = None
    sort_by_hue  = False
    jump_mode    = False   # True while user is typing a name prefix to jump
    jump_buf     = ""

    def colors_for(i: int):
        if i not in cache:
            entry = schemes[i][1]
            cache[i] = entry if isinstance(entry, dict) else _try_load(entry)
        return cache[i]

    def _try_load(entry):
        try:
            return load_fn(entry)
        except Exception:
            return None

    def ui_h() -> int:
        """Scheme rows visible (each scheme = 2 display lines)."""
        return max(1, (os.get_terminal_size().lines - 6) // 2)

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

        sort_label = "hue" if sort_by_hue else "name"
        jump_hint  = f"  /{jump_buf}▌" if jump_mode else ""

        buf = [_HOME]
        if select_mode:
            header = f"  {_BOLD}{prompt}{_RESET}  {_DIM}—  {len(schemes)} schemes · {fc} ★{_RESET}"
            action = "Enter = select"
        else:
            header = f"  {_BOLD}{len(schemes)} schemes{_RESET}  {_DIM}· {fc} ★ · sort: {sort_label}{_RESET}"
            action = "Enter = bookmark"
        buf.append(f"{header}{_EOL}")
        buf.append(f"  {_DIM}Aa normal · Bb bold · Cc selected{_RESET}{_EOL}")
        buf.append(f"  {_DIM}↑↓ jk · {action} · s sort · / jump{jump_hint} · + fetch · q {'cancel' if select_mode else 'done'}{_RESET}{_EOL}")
        buf.append(_EOL)

        for i in range(vtop, end):
            l1, l2 = _row(i, schemes[i][0], colors_for(i),
                           bookmarked=(schemes[i][0] in favorites),
                           selected=(i == cursor))
            buf.append(l1)
            buf.append(l2)

        for _ in range(h - (end - vtop)):
            buf.append(_EOL)
            buf.append(_EOL)

        buf.append(_EOL)
        buf.append(f"  {_DIM}{cursor + 1} / {len(schemes)}{_RESET}{_EOL}")

        sys.stdout.write("\n".join(buf))
        sys.stdout.flush()

    # -------------------------------------------------------------------------
    # Jump helpers
    # -------------------------------------------------------------------------
    def _jump_to(q: str):
        nonlocal cursor
        if not q:
            return
        ql = q.lower()
        for i, (name, _) in enumerate(schemes):
            if name.lower().startswith(ql):
                cursor = i
                scroll()
                return

    # -------------------------------------------------------------------------
    # Sort helpers
    # -------------------------------------------------------------------------
    def _sort_hue():
        nonlocal schemes, cache, cursor, vtop, sort_by_hue
        sys.stdout.write(f"{_HOME}  Loading colors for hue sort…{_EOL}\n")
        sys.stdout.flush()
        for i in range(len(schemes)):
            colors_for(i)
        idx = sorted(range(len(schemes)), key=lambda i: _hue_sort_key(cache.get(i)))
        schemes     = [schemes[i] for i in idx]
        cache       = {j: cache[idx[j]] for j in range(len(idx)) if idx[j] in cache}
        sort_by_hue = True
        cursor = 0
        vtop   = 0

    def _sort_name():
        nonlocal schemes, cache, cursor, vtop, sort_by_hue
        id_map  = {id(s): cache.get(i) for i, s in enumerate(schemes)}
        schemes = list(orig_schemes)
        cache   = {i: id_map[id(s)] for i, s in enumerate(schemes)
                   if id(s) in id_map and id_map[id(s)] is not None}
        sort_by_hue = False
        cursor = 0
        vtop   = 0

    # -------------------------------------------------------------------------
    sys.stdout.write(_HIDE + _CLR)
    sys.stdout.flush()

    try:
        draw()

        while True:
            key = _getch()

            # In jump mode: printable chars extend the query
            if jump_mode and len(key) == 1 and 0x20 <= ord(key) <= 0x7e and key not in ("\x1b",):
                if key == "\x7f" or key == "\x08":
                    jump_buf = jump_buf[:-1]
                elif key == "/":
                    jump_mode = False
                    jump_buf  = ""
                else:
                    jump_buf += key
                    _jump_to(jump_buf)
                draw()
                continue

            if key in ("q", "Q", "\x03"):
                break

            elif key in ("\r", "\n", " "):
                if jump_mode:
                    jump_mode = False
                    jump_buf  = ""
                    draw()
                    continue
                if select_mode:
                    _selected = colors_for(cursor)
                    break
                else:
                    name = schemes[cursor][0]
                    if name in favorites:
                        favorites.discard(name)
                        if live_filter:
                            schemes.pop(cursor)
                            cache = {i: v for i, v in cache.items() if i < cursor}
                            if not schemes:
                                break
                            cursor = min(cursor, len(schemes) - 1)
                    else:
                        favorites.add(name)
                    draw()

            elif key in ("\x1b[A", "\x1bOA", "k"):
                cursor = max(0, cursor - 1)
                draw()

            elif key in ("\x1b[B", "\x1bOB", "j"):
                cursor = min(len(schemes) - 1, cursor + 1)
                draw()

            elif key in ("\x1b[5~",):
                cursor = max(0, cursor - ui_h())
                draw()

            elif key in ("\x1b[6~",):
                cursor = min(len(schemes) - 1, cursor + ui_h())
                draw()

            elif key in ("g", "\x1b[H", "\x1b[1~"):
                cursor = 0
                draw()

            elif key in ("G", "\x1b[F", "\x1b[4~"):
                cursor = len(schemes) - 1
                draw()

            elif key in ("s", "S"):
                if sort_by_hue:
                    _sort_name()
                else:
                    _sort_hue()
                draw()

            elif key == "/":
                jump_mode = not jump_mode
                if not jump_mode:
                    jump_buf = ""
                draw()

            elif key == "\x1b":
                if jump_mode:
                    jump_mode = False
                    jump_buf  = ""
                    draw()

            elif key in ("\x7f", "\x08"):
                if jump_mode and jump_buf:
                    jump_buf = jump_buf[:-1]
                    _jump_to(jump_buf)
                    draw()

            elif key == "+":
                # Fetch a scheme by name without quitting the browser
                sys.stdout.write(_SHOW)
                sys.stdout.flush()
                rows = os.get_terminal_size().lines
                sys.stdout.write(f"\033[{rows};1H\033[K")
                sys.stdout.flush()
                try:
                    name = input("  Fetch scheme: ").strip()
                except (EOFError, KeyboardInterrupt):
                    name = ""
                sys.stdout.write(_HIDE)
                sys.stdout.flush()
                if name:
                    try:
                        from .fetch import fetch_scheme
                        path = fetch_scheme(name)
                        entry = str(path)
                        schemes.append((name, entry))
                        orig_schemes.append((name, entry))
                    except Exception:
                        pass
                draw()

    finally:
        sys.stdout.write(_SHOW + _CLR + _HOME)
        sys.stdout.flush()

    return _selected if select_mode else favorites
