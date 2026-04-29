---
description: Manage and tune mondrian — the iTerm2 color hook for Claude Code.
---

<!-- INSTALLATION
     Copy or symlink this file so Claude Code can find it:

       # Option A — symlink (stays up to date when the repo changes)
       mkdir -p ~/.claude/commands
       ln -sf /Users/mario/dev/mondrian/mondrian.md ~/.claude/commands/mondrian.md

       # Option B — copy
       mkdir -p ~/.claude/commands
       cp /Users/mario/dev/mondrian/mondrian.md ~/.claude/commands/mondrian.md

     Then invoke with /mondrian <request> inside any Claude Code session.
-->

You are helping the user tune **mondrian**, a tool that changes iTerm2's terminal background color in real time based on Claude Code's state.

The user's request is: **$ARGUMENTS**

---

## What mondrian does

| State | When | Default color |
|---|---|---|
| **Waiting** | After Claude finishes (Stop hook) | Original terminal bg |
| **Processing** | The moment the user submits a prompt (UserPromptSubmit) and after tool approval (PreToolUse) | Blue-green |
| **Blocked** | When Claude needs permission (Notification hook, with 3s timing guard) | Red |
| **Pause** | After idle timeout or `mondrian pause` | Custom dim color |

Colors are set via iTerm2's `SetColors` OSC escape: `\033]1337;SetColors=bg=HEX,...\007`

---

## Config file — `~/.mondrian.json`

```json
{
  "source_profile": {"guid": "...", "name": "My Profile"},
  "palette": {
    "direction": "interactive",
    "waiting": "#15191E",
    "active":  "#245032",
    "blocked": "#762423"
  },
  "waiting_colors":  {"bg": "#15191E", "fg": "#DCDCDC", "bold": "#DCDCDC", "selbg": "#B3D7FF",  "selfg": "#000000"},
  "active_colors":   {"bg": "#245032", "fg": "#F8F8F8",  "bold": "#F8F8F8",  "selbg": "#336442",  "selfg": "#F8F8F8"},
  "blocked_colors":  {"bg": "#762423", "fg": "#FFFFFF",  "bold": "#FF9C44",  "selbg": "#073642",  "selfg": "#FFFFFF"},
  "pause_colors":    {"bg": "#1A1A2E", "fg": "#888899",  "bold": "#888899",  "selbg": "#2A2A3E",  "selfg": "#888899"},
  "fg":    "#DCDCDC",
  "selbg": "#B3D7FF",
  "selfg": "#000000",
  "transparency":    {"waiting": 0.0, "active": 0.35},
  "active_is_clone": false,
  "blocked_enabled": true,
  "blocked_expire":  90,
  "pause_timeout":   3600
}
```

**Rules for color dicts:**
- Every `*_colors` dict must have all five keys: `bg`, `fg`, `bold`, `selbg`, `selfg`
- `bold` must always equal `fg` (prevents white-on-light-bg rendering bug)
- `palette.waiting/active/blocked` are the bg hex values — keep them in sync with `*_colors.bg`

**Optional keys** (omit to disable):
- `transparency` — omit to disable all transparency fading
- `blocked_enabled: false` — omit the Notification hook entirely
- `blocked_expire` — seconds before blocked auto-clears (0 or omit = never)
- `pause_colors` + `pause_timeout` — omit to disable idle pause state
- `active_is_clone: true` — processing bg = waiting bg (transparency-only signal)

---

## CLI commands

```
mondrian configure    Full interactive setup (all phases)
mondrian edit         Interactive tweak menu (change one state at a time)
mondrian apply        Re-install hooks from current ~/.mondrian.json (no prompts)
mondrian status       Show current config and hook installation state
mondrian pause        Manually set terminal to pause/parked color
mondrian log <msg>    Append a note to today's log (for flagging issues)
mondrian logs         Show today's log (or most recent day's log)
mondrian fetch <name> Download a scheme by name to ~/.mondrian/schemes/
mondrian fetch --all  Download all ~500 schemes from iTerm2-Color-Schemes
mondrian browse       Full-screen scheme browser (arrow keys, bookmarks)
mondrian reset        Remove hooks, delete config, restore original colors
mondrian uninstall    Remove hooks only (keep config)
```

If `mondrian` is not on PATH, use `python3 /Users/mario/dev/mondrian/mondrian.py <command>`.

---

## Common in-session tasks

### Change processing (active) color

1. Edit `~/.mondrian.json` — set `active_colors.bg` to the new hex, then derive the other fields:
   ```python
   from lib.colors import hex_to_srgb, derive_state_colors, srgb_to_hex
   from lib.iterm import load_profile
   # derive from new bg + existing fg + existing selbg
   new_colors = derive_state_colors(
       hex_to_srgb("#245032"),           # new bg
       hex_to_srgb(config["fg"]),        # fg from config root
       hex_to_srgb(config["selbg"]),     # selbg from config root
   )
   # new_colors = {"bg": hex, "fg": hex, "bold": hex, "selbg": hex, "selfg": hex}
   ```
   Or just set all five manually, keeping `bold == fg`.
2. Update `palette.active` to match `active_colors.bg`.
3. Run `mondrian apply`.

### Change blocked color

Same as above but edit `blocked_colors` and `palette.blocked`.

### Turn off transparency

Remove the `transparency` key from `~/.mondrian.json`, then run `mondrian apply`.

### Set transparency level

Edit `transparency.active` (float, 0.0=opaque → 1.0=clear). Common value: 0.35.
`transparency.waiting` should stay 0.0 (opaque at rest).
Then run `mondrian apply`.

### Disable blocked indicator

Set `"blocked_enabled": false` in `~/.mondrian.json`, then run `mondrian apply`.
This removes the Notification hook entirely — terminal never goes red.

### Auto-clear blocked after N seconds

Set `"blocked_expire": 60` (seconds) and run `mondrian apply`.

### Enable/configure pause state

Add to `~/.mondrian.json`:
```json
"pause_colors": {"bg": "#HEX", "fg": "#HEX", "bold": "#HEX", "selbg": "#HEX", "selfg": "#HEX"},
"pause_timeout": 3600
```
Then run `mondrian apply`. Use `mondrian pause` to activate immediately.

### Use transparency-only processing signal

Set `"active_is_clone": true` in config and ensure `transparency` is configured.
`install_hooks()` will auto-derive a visible fallback if transparency is later removed.
Run `mondrian apply`.

### Apply a named scheme to one state

1. Run `mondrian fetch <SchemeName>` to download it (if not already in `~/.mondrian/schemes/`)
2. Load it in Python: `from lib.colors import load_itermcolors; c = load_itermcolors(Path("~/.mondrian/schemes/SchemeName.itermcolors").expanduser())`
3. Write those colors into the appropriate `*_colors` key in `~/.mondrian.json`
4. Run `mondrian apply`

---

## Logging and debugging

Hooks write timestamped events to `~/.mondrian/logs/YYYY-MM-DD.log`.

```
18:43:01 UserPromptSubmit: active
18:43:45 Stop: waiting
18:43:45 Notification: suppress-marker        ← end-of-turn notification suppressed
18:52:10 Notification: blocked                ← genuine permission request
18:52:14 PreToolUse: active
```

**Flag an issue for review:**
```
mondrian log 'terminal stayed active for 30s after Stop fired at 18:43'
```

**View logs:**
```
mondrian logs
```

Log entries appear alongside hook events so you can correlate timing issues.

---

## Diagnosing problems

**Colors not changing at all:**
Run `mondrian status` — hooks must show ✓. Test the escape manually:
```sh
printf '\033]1337;SetColors=bg=FF0000\007' > /dev/tty
```
Background should turn red.

**Terminal stuck in active (blue) state:**
The Stop hook may have failed. Restore manually:
```sh
printf '\033]1337;SetColors=bg=15191E,fg=DCDCDC,bold=DCDCDC,selbg=B3D7FF,selfg=000000\007' > /dev/tty
```
(Use your actual waiting bg hex from `~/.mondrian.json`.)

**Terminal stuck red (blocked):**
```sh
rm -f /tmp/.mondrian_stop /tmp/.mondrian_suppress /tmp/.mondrian_blocked
```
Then send any message to Claude — the UserPromptSubmit hook resets state.

**Transparency bleeding to other windows:**
This should be fixed (hooks now use `$ITERM_SESSION_ID` to target the specific session).
If it recurs, log it: `mondrian log 'transparency bled to other window at HH:MM'`

**Wrong colors detected during configure:**
Run `mondrian reset`, reopen the terminal, then `mondrian configure` fresh.
(The plist stores pre-transparency values; mondrian uses OSC 11/10 live queries instead.)

---

## Color derivation (Python API)

```python
from lib.colors import (
    hex_to_srgb, srgb_to_hex, srgb_to_hsl,
    derive_palette, derive_state_colors,
)

# Derive fg/bold/selbg/selfg from a background hex
bg_srgb = hex_to_srgb("#245032")
fg_srgb = hex_to_srgb("#DCDCDC")   # from config["fg"]
sb_srgb = hex_to_srgb("#B3D7FF")   # from config["selbg"]

colors = derive_state_colors(bg_srgb, fg_srgb, sb_srgb)
# → {"bg": "#245032", "fg": "#...", "bold": "#...", "selbg": "#...", "selfg": "#..."}

# Derive a full palette (active + blocked) from a background
pal = derive_palette(bg_srgb)
# pal["B"]["active"]  → sRGB tuple for processing bg
# pal["B"]["blocked"] → sRGB tuple for blocked bg
```

---

## Hook events reference

| Hook event | mondrian action |
|---|---|
| `UserPromptSubmit` | → Processing colors; clears suppress marker; resets stop timestamp to 0; cancels idle timer |
| `PreToolUse` | → Processing colors (snaps back from red immediately after user approves a tool) |
| `Stop` | Writes suppress marker (first!), writes timestamp, → Waiting colors; starts idle timer if pause configured |
| `Notification` | Checks suppress marker (remove + skip if found); else checks 3s timing guard; → Blocked if >3s old |

The 3-second guard on Notification filters the spurious end-of-turn notification that Claude Code fires after every normal Stop.

---

## After any JSON edit

Always run `mondrian apply` to push changes to `~/.claude/settings.json` (the hooks) and the Dynamic Profiles. Changes take effect on the next Claude Code hook event (next prompt submit, tool use, or response).
