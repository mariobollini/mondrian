#!/usr/bin/env python3
"""
mondrian — iTerm2 session-state colorizer for Claude Code

Commands:
  configure   Auto-derive palette from your terminal, then apply
  apply       Re-apply the saved palette without reconfiguring
  status      Show current install state
  fetch       Download schemes from iTerm2-Color-Schemes  (fetch --all for everything)
  browse      Browse your local scheme library with color swatches
  reset       Restore terminal colors and remove all mondrian config
  uninstall   Alias for reset
"""

import json
import os
import sys
from pathlib import Path

CONFIG_PATH = Path("~/.mondrian.json").expanduser()


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def _save_config(data: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _pick_transparency(query_fn, required: bool = False) -> dict:
    """Ask whether to enable transparency fading; return config dict or {}."""
    print()
    if required:
        print("  Direction D has no color delta — transparency fade is required.")
    else:
        try:
            raw = input("  Add transparency fade (terminal fades when Claude is working)? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return {}
        if raw != "y":
            return {}

    current = query_fn()
    if current is None:
        print("  (Could not read current transparency via AppleScript — defaulting to 0)")
        current = 0.0

    suggested = round(min(current + 0.35, 0.85), 2)
    print(f"  Current transparency : {current:.0%}  (0% = opaque, 100% = clear)")
    try:
        raw = input(f"  Active (working) transparency [{suggested:.0%}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return {}

    if raw:
        raw = raw.rstrip("%")
        try:
            active_alpha = float(raw) / 100 if float(raw) > 1 else float(raw)
        except ValueError:
            print("  Invalid value, skipping transparency.")
            return {}
    else:
        active_alpha = suggested

    active_alpha = max(0.0, min(1.0, active_alpha))
    print(f"  Waiting: {current:.0%} opacity → Active: {active_alpha:.0%} opacity")
    return {"waiting": round(current, 3), "active": round(active_alpha, 3)}


def cmd_configure() -> None:
    from lib.iterm import read_profile_colors, write_dynamic_profiles, query_terminal_transparency
    from lib.hooks import install_hooks
    from lib.chat import pick_direction_interactively
    from lib.colors import srgb_to_hex, hex_to_srgb

    print("\n  mondrian configure\n")

    profile = read_profile_colors()
    print(f"  Detected profile : {profile['name']}")
    print(f"  Background       : {srgb_to_hex(*profile['bg'])}")
    print(f"  Foreground       : {srgb_to_hex(*profile['fg'])}")

    waiting, active, blocked, label, custom_colors, base_overrides = pick_direction_interactively(
        bg=profile["bg"],
        fg=profile["fg"],
    )

    if custom_colors:
        w_hex = custom_colors["waiting"]["bg"]
        a_hex = custom_colors["active"]["bg"]
        b_hex = custom_colors["blocked"]["bg"]
        transparency_required = (w_hex == a_hex)
    else:
        transparency_required = (active == waiting)

    transparency_config = _pick_transparency(query_terminal_transparency, required=transparency_required)

    # Build config and resolve the rgb tuples needed for Dynamic Profiles
    if custom_colors:
        config_data = {
            "source_profile": {"guid": profile["guid"], "name": profile["name"]},
            "palette": {
                "direction": "custom",
                "waiting": w_hex,
                "active":  a_hex,
                "blocked": b_hex,
            },
            "waiting_colors": custom_colors["waiting"],
            "active_colors":  custom_colors["active"],
            "blocked_colors": custom_colors["blocked"],
            "fg":    custom_colors["waiting"]["fg"],
            "selbg": custom_colors["waiting"]["selbg"],
            "selfg": custom_colors["waiting"]["selfg"],
        }
        dp_waiting = hex_to_srgb(w_hex)
        dp_active  = hex_to_srgb(a_hex)
        dp_blocked = hex_to_srgb(b_hex)
        dp_fg      = hex_to_srgb(custom_colors["waiting"]["fg"])
    else:
        # When the user based A-D derivation on an iTerm2 scheme, use that
        # scheme's fg/selbg/selfg rather than the detected profile values.
        fg_hex    = base_overrides["fg"]    if base_overrides else srgb_to_hex(*profile["fg"])
        selbg_hex = base_overrides["selbg"] if base_overrides else srgb_to_hex(*profile["selbg"])
        selfg_hex = base_overrides["selfg"] if base_overrides else srgb_to_hex(*profile["selfg"])
        config_data = {
            "source_profile": {"guid": profile["guid"], "name": profile["name"]},
            "palette": {
                "direction": label,
                "waiting": srgb_to_hex(*waiting),
                "active":  srgb_to_hex(*active),
                "blocked": srgb_to_hex(*blocked),
            },
            "fg":    fg_hex,
            "selbg": selbg_hex,
            "selfg": selfg_hex,
        }
        dp_waiting, dp_active, dp_blocked = waiting, active, blocked
        dp_fg = hex_to_srgb(fg_hex)

    if transparency_config:
        config_data["transparency"] = transparency_config

    # Optional: auto-expire the blocked/red state after N seconds
    print()
    try:
        raw = input(
            "  Auto-clear blocked/red after N seconds? [e.g. 90, or Enter to skip]: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        raw = ""
    if raw:
        try:
            config_data["blocked_expire"] = max(10, int(raw))
            print(f"  Blocked state will auto-clear after {config_data['blocked_expire']}s.")
        except ValueError:
            pass

    # Persist config first so install_hooks reads the correct palette
    _save_config(config_data)

    # Write Dynamic Profiles
    path = write_dynamic_profiles(
        parent_guid=profile["guid"],
        waiting=dp_waiting,
        active=dp_active,
        blocked=dp_blocked,
        fg=dp_fg,
    )
    print(f"  Dynamic Profiles → {path}")

    # Patch hooks (reads from the config we just saved)
    install_hooks()
    print("  Hooks            → ~/.claude/settings.json")

    # Optional shell focus-restore hook
    from lib.shell import install_shell_hook, shell_hook_installed
    print()
    if not shell_hook_installed():
        try:
            raw = input(
                "  Clear red on focus (adds precmd hook to shell rc)? [y/N]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            raw = ""
        if raw == "y":
            rc = install_shell_hook()
            print(f"  Shell hook       → {rc}")
            print(f"  Run: source {rc}  (or restart shell)")
    else:
        print("  Shell focus hook already installed.")

    print("\n  Done. Open a new iTerm2 session to see it in action.\n")


def cmd_apply() -> None:
    from lib.iterm import read_profile_colors, write_dynamic_profiles
    from lib.hooks import install_hooks
    from lib.colors import hex_to_srgb, srgb_to_hex

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
        waiting=waiting,
        active=active,
        blocked=blocked,
        fg=fg,
    )
    install_hooks()
    print(f"  Applied palette to {path} and hooks.")


def cmd_status() -> None:
    from lib.iterm import PROFILE_FILE
    from lib.hooks import hooks_installed
    from lib.colors import srgb_to_hex

    config = _load_config()
    print()
    print("  mondrian status")
    print()

    if config:
        p = config["palette"]
        print(f"  Palette direction : {p.get('direction', '—')}")
        print(f"  Waiting  : {p['waiting']}")
        print(f"  Active   : {p['active']}")
        print(f"  Blocked  : {p['blocked']}")
    else:
        print("  No saved config. Run: mondrian configure")

    print()
    print(f"  Dynamic Profiles : {'✓' if PROFILE_FILE.exists() else '✗'} {PROFILE_FILE}")
    print(f"  Hooks installed  : {'✓' if hooks_installed() else '✗'}")
    print()


def _restore_terminal_now(config: dict) -> None:
    """Send the waiting-state colors and transparency to the live terminal immediately."""
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
             f"tell application \"iTerm2\" to tell current session of "
             f"current window to set transparency to {waiting_alpha:.3f}"],
            capture_output=True,
        )


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
        name = " ".join(args)  # allow multi-word names without quoting
        print(f"\n  Fetching '{name}' …")
        try:
            path = fetch_scheme(name)
            print(f"  Saved → {path}\n")
        except Exception as e:
            print(f"  Failed: {e}\n", file=sys.stderr)
            sys.exit(1)


def cmd_browse() -> None:
    from lib.chat import _get_all_schemes
    from lib.colors import load_itermcolors
    from lib.browse import run_browser
    from lib.fetch import save_favorites

    all_schemes, favorites = _get_all_schemes()
    if not all_schemes:
        print(f"\n  Library is empty. Run: mondrian fetch --all\n")
        return

    fav_orig  = set(favorites)
    fav_count = sum(1 for n, _ in all_schemes if n in favorites)

    if fav_count:
        print(f"\n  Browse  [A] all ({len(all_schemes)})  [F] favorites ({fav_count})", end="  ")
        try:
            mode = input().strip().upper()
        except (EOFError, KeyboardInterrupt):
            mode = "A"
        fav_mode = mode == "F"
        schemes  = [(n, p) for n, p in all_schemes if n in favorites] if fav_mode else all_schemes
    else:
        fav_mode = False
        schemes  = all_schemes

    favorites = run_browser(schemes, favorites, load_itermcolors, live_filter=fav_mode)

    if favorites != fav_orig:
        save_favorites(favorites)
        added   = favorites - fav_orig
        removed = fav_orig - favorites
        if added:
            for n in sorted(added):
                print(f"  ★ {n}")
        if removed:
            for n in sorted(removed):
                print(f"  ✗ {n}")
        print(f"\n  Bookmarks saved — {len(favorites)} total.\n")
    else:
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


COMMANDS = {
    "configure": cmd_configure,
    "apply":     cmd_apply,
    "status":    cmd_status,
    "fetch":     cmd_fetch,
    "browse":    cmd_browse,
    "reset":     cmd_reset,
    "uninstall": cmd_uninstall,
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    if cmd not in COMMANDS:
        print(f"  Unknown command: {cmd}", file=sys.stderr)
        print(f"  Available: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)

    COMMANDS[cmd]()


if __name__ == "__main__":
    main()
