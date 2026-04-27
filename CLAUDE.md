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
| `lib/chat.py` | Phase-by-phase configure flow (Normal → Processing → Blocked → Transparency → Review) |
| `lib/picker.py` | Hue grid picker, closest-scheme search, `pick_state_color()`, ANSI swatch helpers |
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
| `/tmp/.mondrian_suppress` | Stop writes `1` here (before the timestamp); Notification removes it on sight — single-use guard that prevents the end-of-turn Notification race |

---

## Architecture: how the hooks work

```
User submits prompt
  → UserPromptSubmit hook fires
  → printf SetColors (active bg/fg/bold/selbg/selfg) > /dev/tty
  → optional: osascript sets transparency

Claude uses a tool requiring permission
  → Notification hook fires
  → primary guard: if /tmp/.mondrian_suppress exists → remove it → suppressed
  → fallback guard: $(date +%s) - $(cat /tmp/.mondrian_stop) > 3?
  → if yes: printf SetColors (blocked/red) > /dev/tty
  → if no: suppressed (end-of-response spurious notification)

User approves permission
  → PreToolUse hook fires
  → printf SetColors (active) > /dev/tty  ← snaps back from red immediately

Claude finishes responding
  → Stop hook fires
  → echo 1 > /tmp/.mondrian_suppress  ← written FIRST so concurrent Notification sees it
  → echo $(date +%s) > /tmp/.mondrian_stop
  → printf SetColors (waiting/original) > /dev/tty
  → optional: osascript restores transparency

User submits next prompt
  → UserPromptSubmit hook fires
  → rm -f /tmp/.mondrian_suppress  ← clears stale suppress (if no Notification ever consumed it)
  → echo 0 > /tmp/.mondrian_stop
  → printf SetColors (active) > /dev/tty
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
  → configure_phases() in lib/chat.py
  → Phase 1: Normal — show current colors, optional customize
  → Phase 2: Processing — pick_state_color() (hue grid → closest schemes → select)
  → Phase 3: Blocked — same picker, or disable blocked indicator entirely
  → Phase 4: Transparency — optional fade while Claude works
  → Review + confirm
  → install_hooks()  →  bakes hex values into shell one-liners in settings.json
```

`pick_state_color()` flow (in `lib/picker.py`):
```
Hue grid (9 hues + custom hex + Enter=auto)
  → bg_distance() scores all schemes by color proximity to chosen hue
  → top 6 closest shown with text swatches + hex
  → user picks 1-6, or [j] just use the hex, or [m] full browser, or [b] back
```

`install_hooks()` always reads `*_colors` dicts from config (all three states always stored as full dicts since the interactive configure redesign).

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

All configs written since the interactive-picker redesign use full color dicts for all three states:

```json
{
  "source_profile": {"guid": "...", "name": "My Profile"},
  "palette": {
    "direction": "interactive",
    "waiting": "#15191E",
    "active":  "#2E3440",
    "blocked": "#762423"
  },
  "waiting_colors": {"bg": "#15191E", "fg": "#DCDCDC", "bold": "#DCDCDC", "selbg": "#B3D7FF", "selfg": "#000000"},
  "active_colors":  {"bg": "#2E3440", "fg": "#CDCECF", "bold": "#CDCECF", "selbg": "#3E4A5B", "selfg": "#CDCECF"},
  "blocked_colors": {"bg": "#762423", "fg": "#FFFFFF",  "bold": "#FF9C44", "selbg": "#073642", "selfg": "#FFFFFF"},
  "fg":    "#DCDCDC",
  "selbg": "#B3D7FF",
  "selfg": "#000000",
  "transparency":    {"waiting": 0.0, "active": 0.35},
  "blocked_enabled": true,
  "blocked_expire":  90
}
```

Optional keys:
- `transparency` — omit to disable fade entirely
- `blocked_enabled: false` — omit the Notification hook entirely (no red state)
- `blocked_expire` — seconds before blocked state auto-clears (0 = off)

`install_hooks()` always reads `*_colors` dicts when present. The `palette.waiting/active/blocked` bg hex strings are kept for quick `mondrian status` display and legacy `mondrian apply` fallback.

---

## Phase-by-phase configure flow

`configure_phases()` in `lib/chat.py`:

1. **Normal** — shows current terminal swatches; optional "Customize?" prompt
2. **Processing** — `pick_state_color()` (hue grid → scheme search → select/browse/hex)
3. **Blocked** — "Enable blocked indicator? [Y/n]" → same picker if yes; if no, Notification hook is not installed and blocked_enabled=false is stored
4. **Transparency** — optional fade; required if processing == waiting (otherwise no visible signal)
5. **Review + confirm** — swatches for all three states side by side

`pick_state_color()` in `lib/picker.py`:
- Hue grid: 9 named hues (1–9) + `h` for raw hex + Enter for auto-derive
- After picking a hue, loads all schemes from `~/.mondrian/schemes/` + iTerm2 Custom Color Presets
- Ranks by `bg_distance()` — type-aware (gray vs colored penalty of 2.5 prevents achromatic false matches)
- Shows top 6 with text swatches; also [j] just use this hex, [m] full browser, [b] back

---

## In-session configuration

Mondrian settings can be changed live from within a Claude Code session without running `mondrian configure`. The user can ask Claude to make changes and Claude will:

1. Read `~/.mondrian.json`
2. Edit the relevant fields (hex values in `*_colors`, `transparency`, `blocked_enabled`, `blocked_expire`, etc.)
3. Run `python /path/to/mondrian.py apply` — which re-installs hooks and updates Dynamic Profiles
4. Changes take effect on the next prompt/tool event

Common in-session requests and what to change:
- "set processing color to X" → edit `active_colors` bg (and derive new fg/bold/selbg/selfg via `derive_state_colors`) + `palette.active`
- "set blocked color to X" → edit `blocked_colors` similarly + `palette.blocked`
- "turn off blocked indicator" → set `blocked_enabled: false`, `mondrian apply` removes the Notification hook
- "set active transparency to 40%" → `transparency.active = 0.40`
- "turn off transparency" → remove `transparency` key entirely
- "auto-clear blocked after 60s" → `blocked_expire: 60`

After editing the JSON, always run `mondrian apply` (or call `install_hooks()` + `write_dynamic_profiles()` directly) to push the changes to the live hooks.

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
Run `mondrian edit` for an interactive tweak menu. Or ask Claude Code directly ("change my processing color to Tokyo Night") — it'll edit `~/.mondrian.json` and run `mondrian apply`. Or edit the JSON manually and run `mondrian apply`.

**Q: How do I use a .itermcolors file I already have?**  
Copy it to `~/.mondrian/schemes/` and it'll appear in the scheme picker next time you run `mondrian configure` or `mondrian edit`. Or run `mondrian configure` and pick from the browser.

**Q: `mondrian fetch` is slow / hitting rate limits.**  
The GitHub Contents API has a 60 req/hour unauthenticated limit, but `fetch --all` only makes one API call (to list schemes) then fetches files directly from `raw.githubusercontent.com` — no rate limit issue there. If it's slow, it's network latency over ~500 files.

**Q: How do I completely remove mondrian?**  
`mondrian reset` — restores your original terminal colors live, removes hooks from `~/.claude/settings.json`, deletes `~/.mondrian.json`, and removes the Dynamic Profiles JSON. Your scheme library in `~/.mondrian/schemes/` and favorites are left intact (delete manually if wanted).

**Q: Why does bold text look wrong in the active/blocked states?**  
`bold` in the SetColors call must equal `fg`. If you're editing colors manually in `~/.mondrian.json`, make sure `bold` and `fg` match in each `*_colors` dict, or re-run `mondrian configure`/`apply` to regenerate.

**Q: Can I use this without iTerm2?**  
The `SetColors` OSC sequence is iTerm2-specific. The transparency AppleScript is also iTerm2-only. The color math and palette derivation are terminal-agnostic, but the hooks and color-setting mechanism would need to be rewritten for other terminals.
