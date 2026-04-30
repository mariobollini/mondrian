#!/usr/bin/env python3
"""
mondrian — iTerm2 session-state colorizer for Claude Code

Run without arguments for an interactive menu, or pass a command directly:

  configure   Set up color states (normal / processing / blocked)
  browse      Explore schemes, manage bookmarks, fetch from library
  status      Show current installation state
  reset       Restore terminal and remove all mondrian config

Advanced:
  apply       Re-apply saved config (after editing ~/.mondrian.json)
  fetch       Download a named scheme:  mondrian fetch Dracula
              Download all schemes:     mondrian fetch --all
"""

import json
import sys
from pathlib import Path

CONFIG_PATH = Path("~/.mondrian.json").expanduser()


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def _save_config(data: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Done summary
# ---------------------------------------------------------------------------

def _print_done_summary(dp_path: Path, shell_rc: "Path | None") -> None:
    from lib.tui import BOLD, DIM, RESET

    home = Path.home()

    def rel(p):
        try:
            return "~/" + str(Path(p).relative_to(home))
        except ValueError:
            return str(p)

    print(f"\n  {BOLD}Applied{RESET}\n")
    rows = [
        ("~/.claude/settings.json",     "hooks  (Submit · PreTool · Stop · Notification)"),
        ("~/.mondrian.json",             "palette config"),
        (rel(dp_path),                   "iTerm2 Dynamic Profiles  (Waiting · Active · Blocked)"),
        ("~/.mondrian/restore_seq.sh",   "focus-restore sequence"),
    ]
    if shell_rc:
        rows.append((rel(shell_rc), "shell precmd hook"))

    col = max(len(r[0]) for r in rows) + 2
    for path, desc in rows:
        print(f"  {DIM}{path:<{col}}{RESET}  {desc}")

    print()
    print(f"  {DIM}To undo everything:{RESET}  mondrian reset")
    print(f"  {DIM}To tweak colors:   {RESET}  mondrian edit")
    print()
    print("  Open a new iTerm2 tab or window to activate.")
    print()
    print(f"  {BOLD}In-session editing{RESET}\n")
    print(f"  {DIM}You can change settings by asking Claude Code directly:{RESET}")
    print('  "set my processing color to Tokyo Night"')
    print('  "turn off the blocked indicator"')
    print('  "change active transparency to 40%"')
    print()
    print(f"  {DIM}Claude will edit ~/.mondrian.json and run mondrian apply.{RESET}")
    print()


# ---------------------------------------------------------------------------
# Restore colors to terminal immediately (used by reset)
# ---------------------------------------------------------------------------

def _restore_terminal_now(config: dict) -> None:
    import subprocess

    if "waiting_colors" in config:
        c = config["waiting_colors"]
    else:
        fg    = config.get("fg",    "#101010")
        selbg = config.get("selbg", "#B3D7FF")
        selfg = config.get("selfg", "#000000")
        c = {
            "bg":    config.get("palette", {}).get("waiting", "#FAFAFA"),
            "fg":    fg,
            "bold":  fg,
            "selbg": selbg,
            "selfg": selfg,
        }

    def s(h): return h.lstrip("#")
    seq = (
        f"\\033]1337;SetColors="
        f"bg={s(c['bg'])},fg={s(c['fg'])},bold={s(c['bold'])},"
        f"selbg={s(c['selbg'])},selfg={s(c['selfg'])}\\007"
    )
    subprocess.run(
        f"printf '{seq}' > /dev/tty 2>/dev/null || printf '{seq}' >&2",
        shell=True,
    )

    waiting_alpha = (config.get("transparency") or {}).get("waiting")
    if waiting_alpha is not None:
        subprocess.run(
            ["osascript", "-e",
             f'tell application "iTerm2" to tell current session of '
             f'current window to set transparency to {waiting_alpha:.3f}'],
            capture_output=True,
        )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_configure() -> None:
    from lib.iterm import read_profile_colors, write_dynamic_profiles
    from lib.hooks import install_hooks
    from lib.chat import configure_phases
    from lib.colors import srgb_to_hex, hex_to_srgb
    from lib.shell import install_shell_hook, shell_hook_installed
    from lib.tui import banner, DIM, RESET

    banner(subtitle="configure")
    print(f"  {DIM}Run  mondrian reset  at any time to undo everything.{RESET}\n")

    profile = read_profile_colors()
    print(f"  Profile    : {profile['name']}")
    print(f"  Background : {srgb_to_hex(*profile['bg'])}")
    print(f"  Foreground : {srgb_to_hex(*profile['fg'])}")

    # Establish waiting colors as the session default so \033[0m restores the
    # right fg/bg during the picker (avoids the "font color shift" artifact).
    _restore_terminal_now({
        "waiting_colors": {
            "bg":    srgb_to_hex(*profile["bg"]),
            "fg":    srgb_to_hex(*profile["fg"]),
            "bold":  srgb_to_hex(*profile["fg"]),
            "selbg": srgb_to_hex(*profile["selbg"]),
            "selfg": srgb_to_hex(*profile["selfg"]),
        }
    })

    result = configure_phases(profile)
    if result is None:
        return
    waiting_colors, active_colors, blocked_colors, transparency_config, blocked_enabled, blocked_expire, pause_colors, pause_timeout = result

    # Build and save config
    active_is_clone = active_colors.get("bg") == waiting_colors.get("bg")
    config_data: dict = {
        "source_profile": {"guid": profile["guid"], "name": profile["name"]},
        "palette": {
            "direction": "interactive",
            "waiting": waiting_colors["bg"],
            "active":  active_colors["bg"],
            "blocked": blocked_colors["bg"],
        },
        "waiting_colors": waiting_colors,
        "active_colors":  active_colors,
        "blocked_colors": blocked_colors,
        "fg":    waiting_colors["fg"],
        "selbg": waiting_colors["selbg"],
        "selfg": waiting_colors["selfg"],
    }
    if transparency_config:
        config_data["transparency"] = transparency_config
    if blocked_expire:
        config_data["blocked_expire"] = blocked_expire
    if not blocked_enabled:
        config_data["blocked_enabled"] = False
    if active_is_clone:
        config_data["active_is_clone"] = True
    if pause_colors:
        config_data["pause_colors"]  = pause_colors
        config_data["pause_timeout"] = pause_timeout

    _save_config(config_data)

    # Dynamic Profiles (bake transparency so new windows open at the right opacity)
    _tr = config_data.get("transparency") or {}
    dp_path = write_dynamic_profiles(
        parent_guid   = profile["guid"],
        waiting       = hex_to_srgb(waiting_colors["bg"]),
        active        = hex_to_srgb(active_colors["bg"]),
        blocked       = hex_to_srgb(blocked_colors["bg"]),
        fg            = hex_to_srgb(waiting_colors["fg"]),
        waiting_alpha = _tr.get("waiting"),
        active_alpha  = _tr.get("active"),
    )

    # Hooks
    install_hooks()

    # Shell focus-restore hook
    shell_rc = None
    print()
    if not shell_hook_installed():
        try:
            raw = input(
                "  Clear red on terminal focus (adds precmd hook to shell rc)? [y/N]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            raw = ""
        if raw == "y":
            shell_rc = install_shell_hook()
    else:
        print("  Shell focus hook already installed.")

    # Snap terminal to the newly configured waiting colors immediately.
    _restore_terminal_now(config_data)

    _print_done_summary(dp_path, shell_rc)


def cmd_edit() -> None:
    from lib.iterm import write_dynamic_profiles, query_terminal_transparency
    from lib.hooks import install_hooks
    from lib.chat import _get_all_schemes, _pick_transparency
    from lib.colors import srgb_to_hex, hex_to_srgb, srgb_to_hsl, derive_palette, derive_state_colors
    from lib.picker import pick_state_color

    config = _load_config()
    if not config:
        print("\n  No config found. Run: mondrian configure\n")
        return

    _schemes = _favs = None

    def _get_schemes():
        nonlocal _schemes, _favs
        if _schemes is None:
            _schemes, _favs = _get_all_schemes()
        return _schemes, _favs

    def _dark():
        wc = config.get("waiting_colors", {})
        return srgb_to_hsl(*hex_to_srgb(wc.get("bg", "#FAFAFA")))[2] < 0.5

    def _remove_transparency():
        config.pop("transparency", None)
        if config.get("active_is_clone"):
            wc2     = config.get("waiting_colors", {})
            fg_t    = hex_to_srgb(wc2.get("fg",    "#101010"))
            selbg_t = hex_to_srgb(wc2.get("selbg", "#B3D7FF"))
            pal     = derive_palette(hex_to_srgb(wc2.get("bg", "#FAFAFA")))
            auto_ac = derive_state_colors(pal["B"]["active"], fg_t, selbg_t)
            config["active_colors"]              = auto_ac
            config.get("palette", {})["active"]  = auto_ac["bg"]
            config.pop("active_is_clone", None)
            print(f"  Clone-waiting mode off — auto-derived active: {auto_ac['bg']}")
        print("  Transparency off.")

    from lib.tui import banner, swatches, BOLD, DIM, RESET

    while True:
        wc  = config.get("waiting_colors",  {})
        ac  = config.get("active_colors",   {})
        bc  = config.get("blocked_colors",  {})
        pc  = config.get("pause_colors")
        tr  = config.get("transparency") or {}
        be  = config.get("blocked_enabled", True)
        exp = config.get("blocked_expire",  0)
        pto = config.get("pause_timeout", 3600)
        is_clone = config.get("active_is_clone", False)

        tr_str  = f"{tr.get('active', 0):.0%} while processing" if tr else "off"
        exp_str = f"{exp}s" if exp else "off"
        be_str  = "on" if be else f"{DIM}off{RESET}"
        ac_str  = "(clone waiting, transparency only)" if is_clone else ac.get("bg", "—")
        pc_str  = pc["bg"] if pc else f"{DIM}off{RESET}"
        pto_str = f"{pto}s" if pc else f"{DIM}—{RESET}"

        w_sw = swatches(wc) if wc else "                "
        a_sw = swatches(ac) if ac else "                "
        b_sw = swatches(bc) if bc else "                "
        p_sw = swatches(pc) if pc else "                "

        banner(
            waiting_hex = wc.get("bg") if wc else None,
            active_hex  = ac.get("bg") if ac else None,
            blocked_hex = bc.get("bg") if bc else None,
            subtitle    = "edit",
        )
        print(f"  {DIM}0{RESET}  {BOLD}[n]{RESET}ormal        {w_sw}  {DIM}{wc.get('bg', '—')}{RESET}")
        print(f"  {DIM}1{RESET}  {BOLD}[p]{RESET}rocessing    {a_sw}  {DIM}{ac_str}{RESET}")
        print(f"  {DIM}2{RESET}  {BOLD}[b]{RESET}locked       {b_sw}  {DIM}{bc.get('bg', '—')}{RESET}  ·  {be_str}")
        print(f"  {DIM}3{RESET}  {BOLD}[o]{RESET}n/off        {DIM}toggle blocked indicator{RESET}")
        print(f"  {DIM}4{RESET}  {BOLD}[t]{RESET}ransparency  {DIM}{tr_str}{RESET}")
        print(f"  {DIM}5{RESET}  {BOLD}[e]{RESET}xpire        {DIM}auto-clear blocked  ·  {exp_str}{RESET}")
        print(f"  {DIM}6{RESET}  {BOLD}[i]{RESET}dle / pause  {p_sw}  {DIM}{pc_str}  ·  {pto_str}{RESET}")
        print()
        print(f"     {BOLD}[a]{RESET}pply and save")
        print(f"     {BOLD}[q]{RESET}uit without saving")
        print()

        try:
            raw = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if raw == "q":
            return

        if raw in ("0", "n"):
            sc, fav = _get_schemes()
            picked = pick_state_color(
                "Normal", sc, fav, wc, _dark(),
                phase_slot="active", other_colors=None,
            )
            if picked:
                config["waiting_colors"]      = picked
                config["palette"]["waiting"]  = picked["bg"]
                config["fg"]    = picked["fg"]
                config["selbg"] = picked["selbg"]
                config["selfg"] = picked["selfg"]
                if config.get("active_is_clone"):
                    config["active_colors"]     = dict(picked)
                    config["palette"]["active"] = picked["bg"]

        elif raw in ("1", "p"):
            sc, fav = _get_schemes()
            picked = pick_state_color(
                "Processing", sc, fav, wc, _dark(), hint="blue [6]",
                phase_slot="active", other_colors=bc, allow_clone=True,
            )
            if picked:
                config["active_colors"]     = picked
                config["palette"]["active"] = picked["bg"]
                if picked.get("bg") == wc.get("bg"):
                    config["active_is_clone"] = True
                    print(f"  {DIM}Clone waiting — transparency will be the only signal.{RESET}\n")
                else:
                    config.pop("active_is_clone", None)

        elif raw in ("2", "b"):
            sc, fav = _get_schemes()
            picked = pick_state_color(
                "Blocked", sc, fav, wc, _dark(), hint="red [1]",
                phase_slot="blocked", other_colors=ac,
            )
            if picked:
                config["blocked_colors"]     = picked
                config["palette"]["blocked"] = picked["bg"]
                config["blocked_enabled"]    = True

        elif raw in ("3", "o"):
            be = not be
            config["blocked_enabled"] = be
            print(f"  Blocked indicator {'enabled' if be else 'disabled'}.")

        elif raw in ("4", "t"):
            if tr:
                cur = tr.get("active", 0)
                print(f"\n  Currently: {cur:.0%} while processing\n")
                print(f"  {BOLD}[a]{RESET}djust   {BOLD}[o]{RESET}ff   Enter = keep\n")
                try:
                    sub = input("  > ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    sub = ""
                if sub == "a":
                    tr_new = _pick_transparency(query_terminal_transparency)
                    if tr_new:
                        config["transparency"] = tr_new
                elif sub == "o":
                    _remove_transparency()
            else:
                tr_new = _pick_transparency(query_terminal_transparency)
                if tr_new:
                    config["transparency"] = tr_new

        elif raw in ("5", "e"):
            try:
                v = input("  Seconds before auto-clear (0 = off): ").strip()
                n = int(v)
                if n <= 0:
                    config.pop("blocked_expire", None)
                    print("  Auto-clear disabled.")
                else:
                    n = max(10, n)
                    config["blocked_expire"] = n
                    print(f"  Will auto-clear after {n}s.")
            except (ValueError, EOFError, KeyboardInterrupt):
                pass

        elif raw in ("6", "i"):
            sc, fav = _get_schemes()
            if pc:
                print(f"\n  Current pause  {pc['bg']}  ·  idle {pto}s\n")
                print(f"  {BOLD}[r]{RESET}e-pick   {BOLD}[t]{RESET}imeout   {BOLD}[d]{RESET}elete   Enter = keep\n")
                try:
                    sub = input("  > ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    sub = ""
                if sub == "r":
                    picked = pick_state_color(
                        "Pause", sc, fav, wc, _dark(), hint="dark/dim [9]",
                        phase_slot="active", other_colors=None,
                    )
                    if picked:
                        config["pause_colors"] = picked
                        print(f"  Pause color updated.")
                elif sub == "t":
                    try:
                        v = input(f"  Idle timeout in seconds [{pto}]: ").strip()
                        n = int(v) if v else pto
                        config["pause_timeout"] = max(60, n)
                        print(f"  Timeout set to {config['pause_timeout']}s.")
                    except (ValueError, EOFError, KeyboardInterrupt):
                        pass
                elif sub == "d":
                    config.pop("pause_colors",  None)
                    config.pop("pause_timeout", None)
                    print("  Pause color removed.")
            else:
                print()
                print("  Pause color: shown when idle for a while, or via  mondrian pause.")
                print()
                picked = pick_state_color(
                    "Pause", sc, fav, wc, _dark(), hint="dark/dim [9]",
                    phase_slot="active", other_colors=None,
                )
                if picked:
                    config["pause_colors"] = picked
                    try:
                        v = input("  Idle timeout in seconds [3600]: ").strip()
                        n = int(v) if v else 3600
                        config["pause_timeout"] = max(60, n)
                    except (ValueError, EOFError, KeyboardInterrupt):
                        config["pause_timeout"] = 3600
                    print(f"  Pause after {config['pause_timeout']}s of inactivity.")

        elif raw == "a":
            _save_config(config)
            install_hooks()
            guid = config.get("source_profile", {}).get("guid")
            if guid and "waiting_colors" in config:
                _tr2 = config.get("transparency") or {}
                dp = write_dynamic_profiles(
                    parent_guid   = guid,
                    waiting       = hex_to_srgb(config["waiting_colors"]["bg"]),
                    active        = hex_to_srgb(config["active_colors"]["bg"]),
                    blocked       = hex_to_srgb(config["blocked_colors"]["bg"]),
                    fg            = hex_to_srgb(config["waiting_colors"]["fg"]),
                    waiting_alpha = _tr2.get("waiting"),
                    active_alpha  = _tr2.get("active"),
                )
                print(f"  Dynamic profiles updated: {dp}")
            _restore_terminal_now(config)
            print("  Applied.\n")
            return


def cmd_apply() -> None:
    from lib.iterm import read_profile_colors, write_dynamic_profiles
    from lib.hooks import install_hooks
    from lib.colors import hex_to_srgb

    config = _load_config()
    if not config:
        print("  No saved config. Run: mondrian configure", file=sys.stderr)
        sys.exit(1)

    palette = config["palette"]
    profile = read_profile_colors()

    waiting = hex_to_srgb(palette["waiting"])
    active  = hex_to_srgb(palette["active"])
    blocked = hex_to_srgb(palette["blocked"])
    fg      = hex_to_srgb(config["fg"])

    _tr = config.get("transparency") or {}
    path = write_dynamic_profiles(
        parent_guid   = config["source_profile"]["guid"],
        waiting       = waiting, active=active, blocked=blocked, fg=fg,
        waiting_alpha = _tr.get("waiting"),
        active_alpha  = _tr.get("active"),
    )
    install_hooks()
    print(f"  Applied palette to {path} and hooks.")


def cmd_status() -> None:
    from lib.iterm import PROFILE_FILE
    from lib.hooks import hooks_installed
    from lib.shell import shell_hook_installed
    from lib.tui import banner, swatches, BOLD, DIM, RESET

    config = _load_config()

    wc = config.get("waiting_colors")
    ac = config.get("active_colors")
    bc = config.get("blocked_colors")

    banner(
        waiting_hex = wc["bg"] if wc else None,
        active_hex  = ac["bg"] if ac else None,
        blocked_hex = bc["bg"] if bc else None,
        subtitle    = "status",
    )

    if config:
        be  = config.get("blocked_enabled", True)
        tr  = config.get("transparency") or {}
        exp = config.get("blocked_expire", 0)

        rows = [
            ("Waiting",    wc, True),
            ("Processing", ac, True),
            ("Blocked",    bc, be),
        ]
        for label, colors, enabled in rows:
            if colors and enabled:
                print(f"  {swatches(colors)}  {label:<12}  {DIM}{colors['bg']}{RESET}")
            elif colors:
                print(f"  {swatches(colors)}  {DIM}{label:<12}  {colors['bg']}  (disabled){RESET}")
            else:
                print(f"  {'—':>12}  {DIM}{label:<12}  —{RESET}")

        print()
        if tr:
            wa = tr.get("waiting", 0)
            aa = tr.get("active", 0)
            print(f"  {DIM}Transparency  {RESET}{wa:.0%} → {aa:.0%} while processing")
        else:
            print(f"  {DIM}Transparency  off{RESET}")
        if exp:
            print(f"  {DIM}Blocked expires{RESET}  {exp}s")
        print()
    else:
        print(f"  No saved config. Run: {BOLD}mondrian configure{RESET}\n")

    def ck(ok): return f"{BOLD}✓{RESET}" if ok else f"{DIM}✗{RESET}"

    print(f"  {ck(PROFILE_FILE.exists())}  Dynamic Profiles   {DIM}{PROFILE_FILE}{RESET}")
    print(f"  {ck(hooks_installed())}  Hooks              {DIM}UserPromptSubmit · PreToolUse · Stop · Notification{RESET}")
    print(f"  {ck(shell_hook_installed())}  Shell hook")
    print()


def cmd_pause() -> None:
    """Manually set the terminal to the pause/parked color."""
    from lib.tui import DIM, RESET
    config = _load_config()
    pause_colors = config.get("pause_colors")
    if not pause_colors:
        print(f"\n  No pause color configured.  Add one via:  mondrian edit  [6]\n")
        return
    import subprocess
    from lib.hooks import _colors_seq, _send_seq
    seq = _send_seq(_colors_seq(**pause_colors))
    subprocess.run(seq, shell=True)
    print(f"\n  Parked  →  {pause_colors['bg']}\n")
    print(f"  {DIM}Next Claude Code message will restore normal colors.{RESET}\n")


def cmd_log() -> None:
    """Append a timestamped note to today's mondrian log.

    Intended for Claude Code to flag moments when behavior seemed wrong:
      mondrian log 'active state stuck for 30s after Stop fired'
    """
    from datetime import datetime
    message = " ".join(sys.argv[2:]).strip()
    if not message:
        print("  Usage: mondrian log <message>")
        print("  Example: mondrian log 'active state stuck after Stop'")
        return
    log_dir = Path("~/.mondrian/logs").expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    log_file = log_dir / f"{now.strftime('%Y-%m-%d')}.log"
    with open(log_file, "a") as f:
        f.write(f"{now.strftime('%H:%M:%S')} NOTE: {message}\n")
    print(f"  Logged → {log_file}")


def cmd_logs() -> None:
    """Show today's mondrian log (falls back to most recent day if no log today)."""
    from datetime import datetime
    log_dir = Path("~/.mondrian/logs").expanduser()

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"{today}.log"

    if not log_file.exists():
        log_files = sorted(log_dir.glob("*.log")) if log_dir.exists() else []
        if log_files:
            log_file = log_files[-1]
            print(f"\n  (No log for {today} — showing {log_file.name})\n")
        else:
            print(f"\n  No mondrian logs found in {log_dir}\n")
            return
    else:
        print(f"\n  {log_file}\n")

    content = log_file.read_text()
    if not content.strip():
        print("  (empty)\n")
        return

    lines = content.splitlines()
    if len(lines) > 60:
        print(f"  (last 60 of {len(lines)} lines)\n")
        lines = lines[-60:]
    for line in lines:
        print(f"  {line}")
    print()


def cmd_reset() -> None:
    from lib.iterm import remove_dynamic_profiles
    from lib.hooks import uninstall_hooks
    from lib.shell import remove_shell_hook

    config = _load_config()
    if config:
        _restore_terminal_now(config)
        print("  Colors restored.")

    remove_dynamic_profiles()
    uninstall_hooks()

    removed_rc = remove_shell_hook()
    for rc in removed_rc:
        print(f"  Shell hook removed from {rc}")

    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()

    for tmp in (
        "/tmp/.mondrian_stop", "/tmp/.mondrian_blocked",
        "/tmp/.mondrian_suppress", "/tmp/.mondrian_idle_start", "/tmp/.mondrian_idle_pid",
    ):
        p = Path(tmp)
        if p.exists():
            p.unlink()

    print("  Hooks removed, config deleted.")
    print()


def cmd_uninstall() -> None:
    cmd_reset()


def cmd_fetch() -> None:
    from lib.fetch import fetch_scheme, fetch_all_schemes, SCHEMES_DIR

    args = sys.argv[2:]
    if not args or args[0] in ("-h", "--help"):
        print("\n  Usage: mondrian fetch <name>")
        print("         mondrian fetch --all\n")
        return

    if args[0] == "--all":
        print(f"\n  Fetching all schemes from iTerm2-Color-Schemes …\n")

        def progress(i, total, name):
            bar = "█" * round(20 * i / total)
            print(f"  [{bar:<20}] {i}/{total}  {name:<35}", end="\r", flush=True)

        ok, total = fetch_all_schemes(on_progress=progress)
        print(f"\n\n  Done. {ok}/{total} schemes saved to {SCHEMES_DIR}\n")
    else:
        name = " ".join(args)
        print(f"\n  Fetching '{name}' …")
        try:
            path = fetch_scheme(name)
            print(f"  Saved → {path}\n")
        except Exception as e:
            print(f"  Failed: {e}\n", file=sys.stderr)
            sys.exit(1)


def _fetch_submenu() -> None:
    from lib.fetch import fetch_scheme, fetch_all_schemes, list_local_schemes, SCHEMES_DIR

    from lib.tui import BOLD, DIM, RESET
    local_count = len(list_local_schemes())
    print(f"\n  Fetch from mbadolato/iTerm2-Color-Schemes")
    print(f"  Library: {local_count} schemes in {SCHEMES_DIR}\n")
    print(f"  {DIM}1{RESET}  {BOLD}[s]{RESET}earch by name  {DIM}e.g. Dracula, Tokyo Night{RESET}")
    print(f"  {DIM}2{RESET}  {BOLD}[f]{RESET}etch all       {DIM}~500 schemes, ~3 MB{RESET}")
    print(f"     {BOLD}[q]{RESET}uit / back")
    print()

    try:
        raw = input("  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if raw in ("1", "s"):
        try:
            name = input("  Name: ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not name:
            return
        print(f"  Fetching '{name}' …")
        try:
            path = fetch_scheme(name)
            print(f"  Saved → {path}\n")
        except Exception as e:
            print(f"  Failed: {e}\n", file=sys.stderr)

    elif raw in ("2", "f"):
        print("\n  Fetching all schemes …\n")

        def progress(i, total, name):
            bar = "█" * round(20 * i / total)
            print(f"  [{bar:<20}] {i}/{total}  {name:<35}", end="\r", flush=True)

        ok, total = fetch_all_schemes(on_progress=progress)
        print(f"\n\n  Done. {ok}/{total} schemes saved to {SCHEMES_DIR}\n")


def cmd_browse() -> None:
    from lib.chat import _get_all_schemes
    from lib.colors import load_itermcolors
    from lib.browse import run_browser
    from lib.fetch import save_favorites, list_local_schemes

    while True:
        all_schemes, favorites = _get_all_schemes()
        lib_count  = len(list_local_schemes())
        fav_count  = sum(1 for n, _ in all_schemes if n in favorites)
        plist_count = len(all_schemes) - lib_count

        parts = [f"{lib_count} library"]
        if plist_count:
            parts.append(f"{plist_count} from iTerm2 prefs")
        total_label = " + ".join(parts)

        from lib.tui import BOLD, DIM, RESET
        print(f"\n  Browse  {total_label}  ·  {fav_count} bookmarked\n")
        print(f"  {BOLD}[a]{RESET}ll schemes")
        print(f"  {BOLD}[f]{RESET}avorites")
        print(f"  {BOLD}[+]{RESET} fetch more from iTerm2-Color-Schemes")
        print(f"  {BOLD}[q]{RESET}uit")
        print()

        try:
            mode = input("  > ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if mode in ("Q", ""):
            return

        if mode == "+":
            _fetch_submenu()
            continue

        fav_mode = mode == "F"
        fav_orig = set(favorites)
        schemes  = [(n, p) for n, p in all_schemes if n in favorites] if fav_mode else all_schemes

        if not schemes:
            print("\n  No schemes yet. Choose [+] to fetch some.\n")
            continue

        new_favorites = run_browser(schemes, favorites, load_itermcolors, live_filter=fav_mode)

        if new_favorites != fav_orig:
            save_favorites(new_favorites)
            added   = new_favorites - fav_orig
            removed = fav_orig - new_favorites
            for n in sorted(added):   print(f"  ★ {n}")
            for n in sorted(removed): print(f"  ✗ {n}")
            print(f"  {len(new_favorites)} bookmarks saved.")
        # Loop back to menu after each browse session


# ---------------------------------------------------------------------------
# Main menu + entry point
# ---------------------------------------------------------------------------

COMMANDS = {
    "configure": cmd_configure,
    "edit":      cmd_edit,
    "apply":     cmd_apply,
    "status":    cmd_status,
    "fetch":     cmd_fetch,
    "browse":    cmd_browse,
    "pause":     cmd_pause,
    "log":       cmd_log,
    "logs":      cmd_logs,
    "reset":     cmd_reset,
    "uninstall": cmd_uninstall,
}


def _show_menu() -> None:
    from lib.tui import banner, swatches, BOLD, DIM, RESET

    config = _load_config()
    wc = config.get("waiting_colors")
    ac = config.get("active_colors")
    bc = config.get("blocked_colors")

    note = "configured ✓" if config else "not configured"
    banner(
        waiting_hex = wc["bg"] if wc else None,
        active_hex  = ac["bg"] if ac else None,
        blocked_hex = bc["bg"] if bc else None,
        note        = note,
    )

    if wc and ac and bc:
        be = config.get("blocked_enabled", True)
        print(f"  {swatches(wc)}  {DIM}Waiting{RESET}")
        print(f"  {swatches(ac)}  {DIM}Processing{RESET}")
        if be:
            print(f"  {swatches(bc)}  {DIM}Blocked{RESET}")
        else:
            print(f"  {swatches(bc)}  {DIM}Blocked  (disabled){RESET}")
        print()

    items = [
        ("1", "configure", "set up color states for Claude Code"),
        ("2", "edit",      "tweak processing/blocked colors, transparency"),
        ("3", "browse",    "explore schemes, manage bookmarks"),
        ("4", "status",    "show current setup"),
        ("5", "reset",     "remove all mondrian config"),
    ]
    for num, cmd, desc in items:
        # Highlight the first letter of the command in brackets
        cmd_fmt = f"{BOLD}[{cmd[0]}]{RESET}{cmd[1:]}"
        pad     = " " * max(1, 12 - len(cmd))
        print(f"  {DIM}{num}{RESET}  {cmd_fmt}{pad}{DIM}{desc}{RESET}")
    print()

    try:
        raw = input("  › ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    dispatch = {
        "1": cmd_configure, "c": cmd_configure,
        "2": cmd_edit,      "e": cmd_edit,
        "3": cmd_browse,    "b": cmd_browse,
        "4": cmd_status,    "s": cmd_status,
        "5": cmd_reset,     "r": cmd_reset,
        # full command names
        "configure": cmd_configure, "edit": cmd_edit,
        "browse": cmd_browse, "status": cmd_status, "reset": cmd_reset,
        "pause": cmd_pause, "log": cmd_log, "logs": cmd_logs,
    }
    dispatch.get(raw, lambda: None)()


def main() -> None:
    args = sys.argv[1:]

    if not args:
        _show_menu()
        return

    if args[0] in ("-h", "--help"):
        print(__doc__)
        return

    cmd = args[0]
    if cmd not in COMMANDS:
        print(f"  Unknown command: {cmd}", file=sys.stderr)
        print(f"  Available: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)

    COMMANDS[cmd]()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(130)
