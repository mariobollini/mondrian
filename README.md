# mondrian

iTerm2 terminal background colorizer for [Claude Code](https://claude.ai/code). Changes your terminal's background color (and optionally transparency) based on what Claude is doing.

| State | When | Default color |
|---|---|---|
| **Waiting** | Your turn — Claude is idle | Your normal terminal color |
| **Active** | Claude is responding | Shifted hue (cool blue or your pick) |
| **Blocked** | Claude needs your input | Rose/red accent |

The blocked state uses a timing guard to suppress the spurious notification that fires at the end of normal responses, so it only appears when Claude genuinely needs something from you.

---

## Requirements

- macOS
- [iTerm2](https://iterm2.com)
- Python 3
- [Claude Code](https://claude.ai/code) CLI

---

## Install

```sh
git clone https://github.com/mariobollini/mondrian.git
cd mondrian
./install.sh
```

`install.sh` runs `mondrian configure` automatically. You can re-run it any time.

---

## Commands

```sh
mondrian configure   # detect terminal colors, pick a palette, install hooks
mondrian apply       # re-apply saved palette without reconfiguring
mondrian status      # show current install state
mondrian uninstall   # remove hooks and config
```

---

## Palette directions

`mondrian configure` derives four directions from your terminal's current background:

| Direction | Active | Blocked | Notes |
|---|---|---|---|
| **A** | Cool blue-gray | Warm amber | Subtle |
| **B** | Cool blue-gray | Rose/red | More contrast |
| **C** | Very subtle cool | Soft lavender | Softest |
| **D** | Same as waiting | Rose/red | Transparency only — no color delta |

Direction **D** requires the transparency fade option. When enabled, the terminal fades to a higher opacity while Claude is working and snaps back when it's your turn.

---

## Transparency fade (optional)

During `configure`, answer `y` to the transparency prompt (or pick direction D, which requires it). You set the target opacity for the active state — the terminal fades to that level while Claude works and returns to your original opacity when done.

Blocked/red state never changes transparency — it only changes color.

---

## How it works

Mondrian installs three [Claude Code hooks](https://docs.anthropic.com/en/docs/claude-code/hooks) into `~/.claude/settings.json`:

- **`UserPromptSubmit`** → sends `SetColors` escape sequence for the active state (+ optional AppleScript transparency)
- **`Stop`** → stamps a timestamp, restores waiting colors and transparency
- **`Notification`** → restores waiting colors only if the `Stop` stamp is older than 3 seconds (filters end-of-response noise); otherwise shows blocked

Terminal colors are set via iTerm2's `\033]1337;SetColors=...` OSC sequence, which sets `bg`, `fg`, `bold`, `selbg`, and `selfg` all at once. Background and foreground detection uses OSC 10/11 queries against the live terminal session, not the iTerm2 plist, so it works correctly regardless of which profile is active or whether transparency is in use.
