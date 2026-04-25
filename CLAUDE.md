# Mondrian — Claude Code Context Guide

This file is a context dump for Claude Code (or any developer) working on this codebase. Read it before editing, extending, or debugging mondrian.

---

## What mondrian does

Mondrian changes iTerm2's terminal background color in real time based on what Claude Code is doing:

| State | Hook | Behavior |
|---|---|---|
| **Waiting** | `Stop` | Restores your original terminal colors |
| **Active** | `UserPromptSubmit`, `PreToolUse` | Shifts to a cool blue-gray (or your chosen scheme) |
| **Blocked** | `Notification` | Shifts to rose/red — Claude needs your attention |

Colors are set via iTerm2's `SetColors` OSC escape sequence. Transparency is optional and set via AppleScript.

---

## File map

### Project files

| File | Role |
|---|---|
| `mondrian.py` | CLI entrypoint. All commands live here as `cmd_*` functions. |
| `lib/colors.py` | Color math (sRGB↔HSL), palette derivation, swatch rendering, `.itermcolors` loading |
| `lib/chat.py` | Interactive palette picker TUI (directions A–E, hex overrides) |
| `lib/browse.py` | Full-screen scheme browser TUI (raw termios, arrow keys, bookmark toggle) |
| `lib/fetch.py` | Remote fetch from mbadolato/iTerm2-Color-Schemes, local library management, favorites |
| `lib/hooks.py` | Builds hook shell commands, reads/writes `~/.claude/settings.json` |
| `lib/iterm.py` | OSC terminal color queries, plist profile reading, Dynamic Profile writing |
| `install.sh` | Symlinks `mondrian.py` to `/usr/local/bin/mondrian`, then runs `configure` |

### System files mondrian touches

| Path | What mondrian does with it |
|---|---|
| `~/.claude/settings.json` | Installs/removes hooks under `hooks.UserPromptSubmit`, `hooks.PreToolUse`, `hooks.Stop`, `hooks.Notification` |
| `~/.mondrian.json` | Saves palette config, fg/selbg/selfg base colors, transparency settings, source profile GUID |
| `~/.mondrian/schemes/` | Local `.itermcolors` library (written by `fetch`, scanned by `browse` and configure E) |
| `~/.mondrian/favorites.json` | List of bookmarked scheme names |
| `~/Library/Application Support/iTerm2/DynamicProfiles/mondrian.json` | Writes three Dynamic Profiles (Mondrian-Waiting, Mondrian-Active, Mondrian-Blocked) |
| `~/Library/Preferences/com.googlecode.iterm2.plist` | **Read-only** — detects the user's active iTerm2 profile |
| `/tmp/.mondrian_stop` | Stop hook writes a Unix timestamp here; Notification hook reads it for the 3-second timing guard |

---

## Architecture: how the hooks work

```
User submits prompt
  → UserPromptSubmit hook fires
  → printf SetColors (active bg/fg/bold/selbg/selfg) > /dev/tty
  → optional: osascript sets transparency

Claude uses a tool requiring permission
  → Notification hook fires
  → checks: $(date +%s) - $(cat /tmp/.mondrian_stop) > 3?
  → if yes: printf SetColors (blocked/red) > /dev/tty
  → if no: suppressed (end-of-response spurious notification)

User approves permission
  → PreToolUse hook fires
  → printf SetColors (active) > /dev/tty  ← snaps back from red immediately

Claude finishes responding
  → Stop hook fires
  → echo $(date +%s) > /tmp/.mondrian_stop
  → printf SetColors (waiting/original) > /dev/tty
  → optional: osascript restores transparency
```

All hook commands are single shell one-liners stored in `~/.claude/settings.json` and tagged with `# Mondrian` for identification and removal.

---

## The SetColors escape sequence

```
\033]1337;SetColors=bg=RRGGBB,fg=RRGGBB,bold=RRGGBB,selbg=RRGGBB,selfg=RRGGBB\007
```

- Sent via `printf '...' > /dev/tty 2>/dev/null || printf '...' >&2`
- Sets background, foreground, bold text, selection background, and selection foreground simultaneously
- `bold` is always set equal to `fg` — this prevents iTerm2 from rendering bold text as bright white on light backgrounds

**Why SetColors and not SetProfile?** `SetProfile` was tried first but failed silently for Dynamic Profiles in this iTerm2 setup. `SetColors` works reliably regardless of profile type.

---

## Color pipeline

```
Terminal bg (OSC 11 query)
  → srgb_to_hsl()
  → derive_palette()  →  4 directions (A/B/C/D) + custom (E)
  → user picks direction
  → derive_state_colors(bg)  →  {bg, fg, bold, selbg, selfg} hex dict per state
  → install_hooks()  →  bakes hex values into shell one-liners in settings.json
```

For custom `.itermcolors` mode (direction E):
```
User picks .itermcolors files (waiting / active / blocked)
  → load_itermcolors()  →  {bg, fg, bold, selbg, selfg} read directly from plist
  → stored in ~/.mondrian.json as waiting_colors / active_colors / blocked_colors
  → install_hooks() reads these directly, bypasses derive_state_colors()
```

`install_hooks()` checks for `*_colors` keys in config first and uses them if present; falls back to deriving from `palette.waiting/active/blocked` hex strings for standard A–D directions.

---

## Color detection

`lib/iterm.py` detects the user's current background via **OSC 11** (background) and **OSC 10** (foreground) terminal queries — not the iTerm2 plist. This matters because:
- Transparency makes the plist value wrong (it stores the pre-transparency color)
- Previous `SetColors` calls aren't reflected in the plist
- Profile changes outside iTerm2 prefs aren't captured

The plist is still read for `selbg`, `selfg`, the profile GUID, and profile name.

Mondrian-managed profiles (`Mondrian-Waiting`, `Mondrian-Active`, `Mondrian-Blocked`) are filtered out from profile detection to avoid self-contamination after a configure run.

---

## Config format (`~/.mondrian.json`)

### Standard mode (directions A–D)
```json
{
  "source_profile": {"guid": "...", "name": "My Profile"},
  "palette": {
    "direction": "cool-blue + rose (contrast)",
    "waiting": "#15191E",
    "active":  "#1A2535",
    "blocked": "#3D1A1A"
  },
  "fg":    "#D7DFEA",
  "selbg": "#6798D5",
  "selfg": "#111111",
  "transparency": {"waiting": 0.0, "active": 0.35}
}
```

### Custom .itermcolors mode (direction E)
Same as above, plus full color dicts:
```json
{
  "waiting_colors": {"bg": "#15191E", "fg": "#D7DFEA", "bold": "#D7DFEA", "selbg": "#6798D5", "selfg": "#111111"},
  "active_colors":  {"bg": "...", ...},
  "blocked_colors": {"bg": "...", ...}
}
```

`install_hooks()` uses `*_colors` dicts directly when present, so the exact per-state fg/bold/selbg/selfg from the `.itermcolors` file is preserved.

---

## Palette directions

| Direction | Active | Blocked | Notes |
|---|---|---|---|
| A | Cool blue-gray (subtle) | Warm amber | Default |
| B | Cool blue-gray (more) | Rose/red | More contrast |
| C | Very subtle cool | Soft lavender | Softest |
| D | Same as waiting | Rose/red | Transparency-only — requires fade |
| E | Custom `.itermcolors` | Custom `.itermcolors` | Full per-state color control |

Direction D requires transparency because there's no color delta — opacity is the only signal.

Dark terminal backgrounds are handled by flipping the lightness delta direction in `derive_palette()`: instead of subtracting from L, dark mode adds to L so the active/blocked states are visibly brighter than the baseline.

---

## Scheme library

- **Source:** `mbadolato/iTerm2-Color-Schemes` on GitHub (~500 schemes, ~1 MB total)
- **Local storage:** `~/.mondrian/schemes/*.itermcolors`
- **Fetch one:** `mondrian fetch Dracula`
- **Fetch all:** `mondrian fetch --all` (progress bar, ~500 files)
- **Browse:** `mondrian browse` → full-screen TUI with arrow-key navigation
- **Favorites:** `~/.mondrian/favorites.json` — toggled with Enter/Space in browser

In configure E, `scan_itermcolors()` checks `~/.mondrian/schemes/` first, then `~/Downloads`, `~/Documents`, `~/Desktop`. External finds can be copied to the library in one step.

---

## The browse TUI (`lib/browse.py`)

Uses raw `termios` + ANSI escape sequences. No curses, no external deps.

- `_getch()` reads a single keypress including multi-byte arrow escape sequences
- Renders by overwriting in place with `\033[H` + `\033[K` per line (no full clear → no flicker)
- `live_filter=True` (favorites mode): removing a bookmark splices the item out of the displayed list immediately; cache indices above the removed slot are invalidated
- Colors are loaded lazily and cached by index; only visible rows are loaded

Keybindings: `↑↓` / `jk` navigate, `Enter`/`Space` toggle bookmark, `PgUp`/`PgDn`, `g`/`G` first/last, `q` quit.

---

## Transparency

- Set via AppleScript: `tell application "iTerm2" to tell current session of current window to set transparency to 0.35`
- Only applied to the **active** state (Claude working) and **waiting** state (restore)
- **Never applied to blocked/red** — the red state should be solid and attention-grabbing
- Current transparency is read via the same AppleScript pattern during configure
- Stored in config as `{"waiting": 0.0, "active": 0.35}` (floats 0.0=opaque, 1.0=clear)

---

## Key design decisions and alternatives considered

### SetColors vs SetProfile
**Tried:** `\033]1337;SetProfile=name\007`  
**Problem:** Failed silently for Dynamic Profiles in this iTerm2 setup  
**Solution:** `SetColors` with explicit hex values — works regardless of profile type, instant

### Full color set vs bg-only
**Problem:** Setting only `bg` via SetColors left fg/bold/selbg/selfg from the previous state, causing white bold text on light blue backgrounds  
**Solution:** Always set all five fields. `bold` is always set equal to `fg`

### OSC 11/10 queries vs plist reading
**Problem:** Plist stores the pre-transparency color value; doesn't reflect `SetColors` calls made since iTerm2 started  
**Solution:** OSC 11 (bg) and OSC 10 (fg) live terminal queries via `/dev/tty`

### 3-second timing guard on Notification
**Problem:** Claude Code fires `Notification` at the end of every normal response (right after `Stop`), not just when genuinely blocked  
**Solution:** `Stop` writes `$(date +%s)` to `/tmp/.mondrian_stop`; `Notification` only shows blocked if the timestamp is >3 seconds old

### PreToolUse hook for permission dialogs
**Problem:** After the user approves a tool permission mid-turn, the terminal stayed red until `Stop` fired at end of turn  
**Solution:** `PreToolUse` fires the moment a tool starts executing (right after approval) and restores the active color

### Transparency on blocked state
**Considered:** Fading transparency on blocked/red state  
**Rejected:** User feedback — the red state should be solid. Transparency is a subtle "working" signal; red is an alert that shouldn't be softened

### Bundling schemes in git repo
**Considered:** Committing all 500 `.itermcolors` files (~1 MB) to the repo  
**Rejected:** Keeps the repo clean. `mondrian fetch --all` downloads them to `~/.mondrian/schemes/` on demand

### curses for the browse TUI
**Considered:** `import curses` for the full-screen browser  
**Rejected:** Raw `termios` + ANSI is simpler, has no setup overhead, and covers the nav we need

---

## Adding a new command

1. Add `def cmd_foo() -> None:` to `mondrian.py`
2. Add `"foo": cmd_foo` to the `COMMANDS` dict
3. Update the module docstring at the top of `mondrian.py`

## Adding a new hook event

1. Add a builder function in `lib/hooks.py` if the command logic is new
2. Add the event to the `hook_commands` dict in `install_hooks()`
3. The existing install/uninstall loop handles any event name automatically (it iterates the dict)
4. Re-run `mondrian apply` to push the new hook to `~/.claude/settings.json`

## Adding a new palette direction

1. Add the direction letter and its `{waiting, active, blocked, label}` dict to the `return` statement in `derive_palette()` in `lib/colors.py`
2. Update the `valid = set(directions.keys()) | {"E"}` line in `pick_direction_interactively()` in `lib/chat.py` — it's automatic if you add to the dict, but update the prompt string too

---

## FAQ

**Q: Colors aren't changing at all.**  
Check `mondrian status` — hooks must show ✓. If hooks are installed but nothing changes, the `printf` to `/dev/tty` may be failing. Test manually: `printf '\033]1337;SetColors=bg=FF0000\007' > /dev/tty` — your terminal background should turn red.

**Q: Terminal is stuck red (blocked) and won't clear.**  
The timing guard timestamp may be stale. Remove it: `rm /tmp/.mondrian_stop`. Then send a message to Claude — the `Stop` hook will reset it.

**Q: The wrong background color was detected during configure.**  
This means either the OSC 11 query failed (mondrian defaults to the plist value) or a Mondrian Dynamic Profile was active at detection time. Run `mondrian reset` then reopen your terminal and run `mondrian configure` fresh.

**Q: Transparency isn't working.**  
AppleScript access to iTerm2 is required. Check System Settings → Privacy & Security → Automation and ensure Terminal (or whatever launched mondrian) can control iTerm2.

**Q: Blocked/red state never appears.**  
The 3-second timing guard requires that `Stop` fires at least 3 seconds before `Notification`. If Claude responds very quickly and then sends a notification, the guard suppresses it. This is intentional — it filters end-of-response noise. Genuine "I need input" blocks (tool permissions, questions) fire the notification well after Stop.

**Q: How do I change my colors without reconfiguring everything?**  
Edit `~/.mondrian.json` directly (change the hex values in `palette` or `*_colors`), then run `mondrian apply`.

**Q: How do I use a .itermcolors file I already have?**  
Run `mondrian configure`, pick `E` at the direction prompt, and enter the file path (tab-complete works). Or copy the file to `~/.mondrian/schemes/` and it'll appear in the library.

**Q: `mondrian fetch` is slow / hitting rate limits.**  
The GitHub Contents API has a 60 req/hour unauthenticated limit, but `fetch --all` only makes one API call (to list schemes) then fetches files directly from `raw.githubusercontent.com` — no rate limit issue there. If it's slow, it's network latency over ~500 files.

**Q: How do I completely remove mondrian?**  
`mondrian reset` — restores your original terminal colors live, removes hooks from `~/.claude/settings.json`, deletes `~/.mondrian.json`, and removes the Dynamic Profiles JSON. Your scheme library in `~/.mondrian/schemes/` and favorites are left intact (delete manually if wanted).

**Q: Why does bold text look wrong in the active/blocked states?**  
`bold` in the SetColors call must equal `fg`. If you're editing colors manually in `~/.mondrian.json`, make sure `bold` and `fg` match in each `*_colors` dict, or re-run `mondrian configure`/`apply` to regenerate.

**Q: Can I use this without iTerm2?**  
The `SetColors` OSC sequence is iTerm2-specific. The transparency AppleScript is also iTerm2-only. The color math and palette derivation are terminal-agnostic, but the hooks and color-setting mechanism would need to be rewritten for other terminals.
