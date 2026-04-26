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
    home = Path.home()

    def rel(p):
        try:
            return "~/" + str(Path(p).relative_to(home))
        except ValueError:
            return str(p)

    print("\n  ── Applied ───────────────────────────────────────────────────────")
    print()
    rows = [
        ("~/.claude/settings.json",         "hooks  (Submit · PreTool · Stop · Notification)"),
        ("~/.mondrian.json",                 "palette config"),
        (rel(dp_path),                       "iTerm2 Dynamic Profiles  (Waiting · Active · Blocked)"),
        ("~/.mondrian/restore_seq.sh",       "focus-restore sequence"),
    ]
    if shell_rc:
        rows.append((rel(shell_rc), "shell precmd hook"))

    col = max(len(r[0]) for r in rows) + 2
    for path, desc in rows:
        print(f"  {path:<{col}}  {desc}")

    print()
    print("  To undo everything:  mondrian reset")
    print("  To tweak colors:     mondrian edit")
    print()
    print("  Open a new iTerm2 tab or window to activate.")
    print()
    print("  ── In-session editing ────────────────────────────────────────────")
    print()
    print("  You can also change settings by asking Claude Code directly:")
    print('  "set my processing color to Tokyo Night"')
    print('  "turn off the blocked indicator"')
    print('  "change active transparency to 40%"')
    print()
    print("  Claude will edit ~/.mondrian.json and run mondrian apply for you.")
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

    print("\n  mondrian configure")
    print("  (Run  mondrian reset  at any time to undo everything.)\n")

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
    waiting_colors, active_colors, blocked_colors, transparency_config, blocked_enabled = result

    # Optional: auto-clear blocked state after N seconds
    print()
    try:
        raw = input(
            "  Auto-clear blocked/red after N seconds? [e.g. 90, or Enter to skip]: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        raw = ""
    blocked_expire = 0
    if raw:
        try:
            blocked_expire = max(10, int(raw))
            print(f"  Blocked state will auto-clear after {blocked_expire}s.")
        except ValueError:
            pass

    # Build and save config
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

    _save_config(config_data)

    # Dynamic Profiles
    dp_path = write_dynamic_profiles(
        parent_guid=profile["guid"],
        waiting=hex_to_srgb(waiting_colors["bg"]),
        active= hex_to_srgb(active_colors["bg"]),
        blocked=hex_to_srgb(blocked_colors["bg"]),
        fg=    hex_to_srgb(waiting_colors["fg"]),
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
    from lib.colors import srgb_to_hex, hex_to_srgb, srgb_to_hsl
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

    while True:
        wc  = config.get("waiting_colors",  {})
        ac  = config.get("active_colors",   {})
        bc  = config.get("blocked_colors",  {})
        tr  = config.get("transparency") or {}
        be  = config.get("blocked_enabled", True)
        exp = config.get("blocked_expire",  0)

        tr_str  = f"{tr.get('active', 0):.0%} while processing" if tr else "off"
        exp_str = f"{exp}s" if exp else "off"
        be_str  = "on" if be else "off"

        print()
        print("  ── Edit ──────────────────────────────────────────────────────────")
        print(f"  [1] Processing color  {ac.get('bg', '—')}")
        print(f"  [2] Blocked color     {bc.get('bg', '—')}  [blocked: {be_str}]")
        print(f"  [3] Toggle blocked    currently {be_str}")
        print(f"  [4] Transparency      {tr_str}")
        print(f"  [5] Auto-clear        {exp_str}")
        print()
        print("  [a] Apply and save")
        print("  [q] Quit without saving")
        print()

        try:
            raw = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if raw == "q":
            return

        if raw == "1":
            sc, fav = _get_schemes()
            picked = pick_state_color("Processing", sc, fav, wc, _dark(), hint="blue [6]")
            if picked:
                config["active_colors"]    = picked
                config["palette"]["active"] = picked["bg"]

        elif raw == "2":
            sc, fav = _get_schemes()
            picked = pick_state_color("Blocked", sc, fav, wc, _dark(), hint="red [1]")
            if picked:
                config["blocked_colors"]     = picked
                config["palette"]["blocked"] = picked["bg"]
                config["blocked_enabled"]    = True

        elif raw == "3":
            be = not be
            config["blocked_enabled"] = be
            print(f"  Blocked indicator {'enabled' if be else 'disabled'}.")

        elif raw == "4":
            tr_new = _pick_transparency(query_terminal_transparency)
            if tr_new:
                config["transparency"] = tr_new
            else:
                config.pop("transparency", None)
                print("  Transparency off.")

        elif raw == "5":
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

        elif raw == "a":
            _save_config(config)
            install_hooks()
            guid = config.get("source_profile", {}).get("guid")
            if guid and "waiting_colors" in config:
                dp = write_dynamic_profiles(
                    parent_guid=guid,
                    waiting=hex_to_srgb(config["waiting_colors"]["bg"]),
                    active= hex_to_srgb(config["active_colors"]["bg"]),
                    blocked=hex_to_srgb(config["blocked_colors"]["bg"]),
                    fg=    hex_to_srgb(config["waiting_colors"]["fg"]),
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

    path = write_dynamic_profiles(
        parent_guid=config["source_profile"]["guid"],
        waiting=waiting, active=active, blocked=blocked, fg=fg,
    )
    install_hooks()
    print(f"  Applied palette to {path} and hooks.")


def cmd_status() -> None:
    from lib.iterm import PROFILE_FILE
    from lib.hooks import hooks_installed
    from lib.shell import shell_hook_installed

    config = _load_config()
    print()
    print("  mondrian status")
    print()

    if config:
        p = config["palette"]
        print(f"  Direction  : {p.get('direction', '—')}")
        print(f"  Normal     : {p['waiting']}")
        print(f"  Processing : {p['active']}")
        print(f"  Blocked    : {p['blocked']}")
        tr = config.get("transparency") or {}
        if tr:
            print(f"  Fade       : {tr.get('waiting',0):.0%} → {tr.get('active',0):.0%} while processing")
    else:
        print("  No saved config. Run: mondrian configure")

    print()
    print(f"  Dynamic Profiles : {'✓' if PROFILE_FILE.exists() else '✗'}  {PROFILE_FILE}")
    print(f"  Hooks installed  : {'✓' if hooks_installed()       else '✗'}")
    print(f"  Shell hook       : {'✓' if shell_hook_installed()  else '✗'}")
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

    for tmp in ("/tmp/.mondrian_stop", "/tmp/.mondrian_blocked"):
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

    local_count = len(list_local_schemes())
    print(f"\n  Fetch from mbadolato/iTerm2-Color-Schemes")
    print(f"  Library: {local_count} schemes in {SCHEMES_DIR}\n")
    print("  [1] Search by name  (e.g. Dracula, Tokyo Night)")
    print("  [2] Fetch all       (~500 schemes, ~3 MB)")
    print("  [q] Back\n")

    try:
        raw = input("  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if raw == "1":
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

    elif raw == "2":
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

        print(f"\n  Browse  {total_label}  ·  {fav_count} bookmarked\n")
        print("  [A] All schemes")
        print("  [F] Favorites")
        print("  [+] Fetch more from iTerm2-Color-Schemes")
        print("  [q] Quit\n")

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
    "reset":     cmd_reset,
    "uninstall": cmd_uninstall,
}


def _show_menu() -> None:
    config = _load_config()
    state  = "configured ✓" if config else "not configured"
    print(f"\n  mondrian  —  iTerm2 colorizer for Claude Code  ({state})\n")
    print("  [1] Configure    set up color states for Claude Code")
    print("  [2] Edit         tweak processing/blocked colors, transparency")
    print("  [3] Browse       explore schemes, manage bookmarks")
    print("  [4] Status       show current setup")
    print("  [5] Reset        remove all mondrian config")
    print()
    try:
        raw = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    {"1": cmd_configure, "2": cmd_edit, "3": cmd_browse, "4": cmd_status, "5": cmd_reset}.get(raw, lambda: None)()


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
    main()
