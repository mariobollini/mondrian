"""
Patch ~/.claude/settings.json to add / remove Mondrian iTerm2 hooks.
"""

import json
from pathlib import Path
from typing import Optional

SETTINGS_PATH   = Path("~/.claude/settings.json").expanduser()
CONFIG_PATH     = Path("~/.mondrian.json").expanduser()

MONDRIAN_MARKER      = "Mondrian"
STOP_TS_FILE         = "/tmp/.mondrian_stop"
BLOCKED_TS_FILE      = "/tmp/.mondrian_blocked"
SUPPRESS_FILE        = "/tmp/.mondrian_suppress"
IDLE_START_FILE      = "/tmp/.mondrian_idle_start"
IDLE_PID_FILE        = "/tmp/.mondrian_idle_pid"
RESTORE_SEQ_PATH     = Path("~/.mondrian/restore_seq.sh").expanduser()
TRANSPARENCY_SCRIPT  = Path("~/.mondrian/set_transparency.sh").expanduser()
_LOG_PATH            = "$HOME/.mondrian/logs/$(date '+%Y-%m-%d').log"

_FS_CHECK = (
    "osascript -e "
    "'tell application \"iTerm2\" to get full screen of current window' "
    "2>/dev/null | grep -q true"
)


# ---------------------------------------------------------------------------
# Low-level command builders
# ---------------------------------------------------------------------------

def _colors_seq(bg: str, fg: str, bold: str, selbg: str, selfg: str) -> str:
    b, f, bo, sb, sf = [c.lstrip("#") for c in (bg, fg, bold, selbg, selfg)]
    return f"\\033]1337;SetColors=bg={b},fg={f},bold={bo},selbg={sb},selfg={sf}\\007"


def _send_seq(seq: str) -> str:
    return f"printf '{seq}' > /dev/tty 2>/dev/null || printf '{seq}' >&2"


def _transparency_stmt(alpha: float) -> str:
    # Delegate to a helper script that targets the session by $ITERM_SESSION_ID
    # rather than 'current window' (which resolves to the focused window and can
    # change the wrong window's transparency when the user switches focus).
    return f"~/.mondrian/set_transparency.sh {alpha:.3f}"


def _log_stmt(event: str, action: str) -> str:
    """Append one log line to the daily log, non-blocking. Never fails."""
    return f"echo \"$(date '+%H:%M:%S') {event}: {action}\" >> {_LOG_PATH} 2>/dev/null"


def _join(*parts: str) -> str:
    """Join shell statements and append the Mondrian marker."""
    return "; ".join(parts) + " # Mondrian"


def _idle_cancel() -> str:
    """Kill any pending idle timer and clear its marker files."""
    return (
        f"kill $(cat {IDLE_PID_FILE} 2>/dev/null) 2>/dev/null; "
        f"rm -f {IDLE_START_FILE} {IDLE_PID_FILE}"
    )


def _pause_idle_start(pause_colors: dict, timeout: int) -> str:
    """Shell snippet: cancel previous idle timer, start a fresh one."""
    send = _send_seq(_colors_seq(**pause_colors))
    log  = _log_stmt("Idle", "pause")
    return (
        f"kill $(cat {IDLE_PID_FILE} 2>/dev/null) 2>/dev/null; "
        f"echo 1 > {IDLE_START_FILE}; "
        f"(sleep {timeout}; "
        f"[ -f {IDLE_START_FILE} ] && {{ {send}; {log}; }}) & "
        f"echo $! > {IDLE_PID_FILE}"
    )


# ---------------------------------------------------------------------------
# Per-event command builders
# ---------------------------------------------------------------------------

def _active_cmd(
    colors: dict,
    alpha: Optional[float] = None,
    fullscreen_colors: Optional[dict] = None,
    reset_stop: bool = False,
    event_name: str = "Active",
    cancel_idle: bool = False,
) -> str:
    """
    UserPromptSubmit / PreToolUse hook.

    reset_stop=True (UserPromptSubmit only): clears the suppress marker and
    resets the stop timestamp to 0 so the Notification timing guard passes.
    cancel_idle=True: kills any pending idle/pause timer (pause feature).
    """
    log   = _log_stmt(event_name, "active")
    send  = _send_seq(_colors_seq(**colors))

    if alpha is None:
        if reset_stop:
            parts = []
            if cancel_idle:
                parts.append(_idle_cancel())
            parts += [f"rm -f {SUPPRESS_FILE}", f"echo 0 > {STOP_TS_FILE}", send, log]
            return _join(*parts)
        return _join(send, log)

    fs_send  = _send_seq(_colors_seq(**(fullscreen_colors or colors)))
    windowed = f"{send}; {_transparency_stmt(alpha)}"

    prefix_parts = []
    if reset_stop:
        if cancel_idle:
            prefix_parts.append(_idle_cancel())
        prefix_parts += [f"rm -f {SUPPRESS_FILE}", f"echo 0 > {STOP_TS_FILE}"]
    prefix = "; ".join(prefix_parts) + "; " if prefix_parts else ""

    return (
        f"{prefix}if {_FS_CHECK}; "
        f"then {fs_send}; {log}; "
        f"else {windowed}; {log}; fi # Mondrian"
    )


def _restore_cmd(
    colors: dict,
    alpha: Optional[float] = None,
    pause_idle_cmd: str = "",
) -> str:
    """Stop hook: write suppress marker first, then stamp time, restore colors.

    The suppress marker is written before anything else so the concurrent
    end-of-turn Notification has the best chance of seeing it before evaluating
    the timing guard.  Notification removes it on sight (single-use), so the
    next genuine blocked notification falls through to the timing-guard fallback.
    """
    suppress      = f"echo 1 > {SUPPRESS_FILE}"
    stamp         = f"echo $(date +%s) > {STOP_TS_FILE}"
    clear_blocked = f"rm -f {BLOCKED_TS_FILE}"
    send          = _send_seq(_colors_seq(**colors))
    log           = _log_stmt("Stop", "waiting")

    if alpha is None:
        parts = [suppress, stamp, clear_blocked, send, log]
        if pause_idle_cmd:
            parts.append(pause_idle_cmd)
        return _join(*parts)

    # Full-screen: no transparency call (no background visible in full-screen)
    suffix = f"; {log}"
    if pause_idle_cmd:
        suffix += f"; {pause_idle_cmd}"
    windowed   = f"{suppress}; {stamp}; {clear_blocked}; {send}; {_transparency_stmt(alpha)}"
    fullscreen = f"{suppress}; {stamp}; {clear_blocked}; {send}"
    return (
        f"if {_FS_CHECK}; "
        f"then {fullscreen}{suffix}; "
        f"else {windowed}{suffix}; fi # Mondrian"
    )


def _blocked_cmd(
    colors: dict,
    waiting_colors: Optional[dict] = None,
    grace: int = 3,
    expire: int = 0,
    waiting_alpha: Optional[float] = None,
) -> str:
    """
    Notification hook: only show blocked if Stop fired >grace seconds ago
    (filters the spurious Notification at the end of normal responses).

    Transparency is intentionally NOT changed here — it persists from whatever
    state the terminal was in (usually active).  This keeps the user's configured
    transparency level across all state transitions.

    If expire > 0, a background subshell auto-restores waiting colors after
    that many seconds — unless Stop or a new UserPromptSubmit has fired.
    """
    send           = _send_seq(_colors_seq(**colors))
    log_blocked    = _log_stmt("Notify", "blocked")
    log_suppress_m = _log_stmt("Notify", "suppress-marker")
    log_suppress_t = _log_stmt("Notify", "suppress-timing")

    if expire > 0 and waiting_colors is not None:
        w_send    = _send_seq(_colors_seq(**waiting_colors))
        w_restore = w_send + (f"; {_transparency_stmt(waiting_alpha)}" if waiting_alpha is not None else "")
        inner = (
            f"NOW=$(date +%s); "
            f"echo $NOW > {BLOCKED_TS_FILE}; "
            f"{send}; {log_blocked}; "
            f"(sleep {expire}; "
            f"BT=$(cat {BLOCKED_TS_FILE} 2>/dev/null||echo 0); "
            f"ST=$(cat {STOP_TS_FILE} 2>/dev/null||echo 0); "
            f'[ "$BT" = "$NOW" ] && [ $ST -lt $BT ] && {w_restore}) &'
        )
    else:
        inner = f"echo $(date +%s) > {BLOCKED_TS_FILE}; {send}; {log_blocked}"

    # Suppress marker (written by Stop) is the primary guard — catches the race
    # where Stop and end-of-turn Notification fire simultaneously.
    # Timing guard is the fallback for late-arriving end-of-turn notifications.
    timing_guard = (
        f"ts=$(cat {STOP_TS_FILE} 2>/dev/null||echo 0); "
        f"if [ $(($(date +%s)-ts)) -gt {grace} ]; "
        f"then {inner}; "
        f"else {log_suppress_t}; fi"
    )
    return (
        f"if [ -f {SUPPRESS_FILE} ]; then rm -f {SUPPRESS_FILE}; {log_suppress_m}; "
        f"else {timing_guard}; fi # Mondrian"
    )


# ---------------------------------------------------------------------------
# Helper scripts
# ---------------------------------------------------------------------------

def _write_restore_seq(waiting_colors: dict) -> None:
    """Write ~/.mondrian/restore_seq.sh used by the shell focus-restore hook."""
    seq = _send_seq(_colors_seq(**waiting_colors))
    RESTORE_SEQ_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESTORE_SEQ_PATH.write_text(
        f"#!/bin/sh\n{seq}\nrm -f {BLOCKED_TS_FILE}\n"
    )
    RESTORE_SEQ_PATH.chmod(0o755)


def _write_transparency_script() -> None:
    """Write ~/.mondrian/set_transparency.sh.

    Targets the specific iTerm2 session via $ITERM_SESSION_ID so transparency
    changes don't bleed onto other windows when the user switches focus.
    Falls back to current-session-of-current-window if the env var is absent.
    """
    TRANSPARENCY_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
    TRANSPARENCY_SCRIPT.write_text(
        "#!/bin/sh\n"
        "# Usage: set_transparency.sh <alpha>  (0.0=opaque, 1.0=clear)\n"
        "if [ -n \"$ITERM_SESSION_ID\" ]; then\n"
        "  osascript -e \"tell application \\\"iTerm2\\\" to set transparency of "
        "(first session of (windows) whose unique ID is \\\"$ITERM_SESSION_ID\\\") "
        "to $1\" 2>/dev/null\n"
        "else\n"
        "  osascript -e 'tell application \"iTerm2\" to "
        "tell current session of current window to set transparency to '\"$1\" 2>/dev/null\n"
        "fi\n"
    )
    TRANSPARENCY_SCRIPT.chmod(0o755)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    return {}


def _save_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _make_hook_entry(command: str) -> dict:
    return {
        "matcher": "",
        "hooks": [{"type": "command", "command": command}],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install_hooks(
    active_colors:  Optional[dict]  = None,
    blocked_colors: Optional[dict]  = None,
    waiting_colors: Optional[dict]  = None,
    active_alpha:   Optional[float] = None,
    waiting_alpha:  Optional[float] = None,
) -> None:
    """
    Install hooks for all three states.  Colors and transparency values can be
    passed in directly or are read from ~/.mondrian.json.
    """
    from .colors import hex_to_srgb, derive_state_colors

    # Ensure support directories and scripts exist
    Path("~/.mondrian/logs").expanduser().mkdir(parents=True, exist_ok=True)
    _write_transparency_script()

    config  = _load_config()
    palette = config.get("palette", {})

    fg_base_hex    = config.get("fg",    "#101010")
    selbg_base_hex = config.get("selbg", "#B3D7FF")
    selfg_base_hex = config.get("selfg", "#000000")

    fg_base    = hex_to_srgb(fg_base_hex)
    selbg_base = hex_to_srgb(selbg_base_hex)

    if active_colors is None:
        if "active_colors" in config:
            active_colors = config["active_colors"]
        else:
            active_hex    = palette.get("active",  "#D6DAE1")
            active_colors = derive_state_colors(hex_to_srgb(active_hex), fg_base, selbg_base)

    if blocked_colors is None:
        if "blocked_colors" in config:
            blocked_colors = config["blocked_colors"]
        else:
            blocked_hex    = palette.get("blocked", "#F9E0DC")
            blocked_colors = derive_state_colors(hex_to_srgb(blocked_hex), fg_base, selbg_base)

    if waiting_colors is None:
        if "waiting_colors" in config:
            waiting_colors = config["waiting_colors"]
        else:
            waiting_hex    = palette.get("waiting", "#FAFAFA")
            waiting_colors = {
                "bg":    waiting_hex,
                "fg":    fg_base_hex,
                "bold":  fg_base_hex,
                "selbg": selbg_base_hex,
                "selfg": selfg_base_hex,
            }

    # Transparency (optional)
    tr = config.get("transparency") or {}
    if active_alpha  is None: active_alpha  = tr.get("active")
    if waiting_alpha is None: waiting_alpha = tr.get("waiting")

    # Clone-waiting mode: active color = waiting color, transparency is the only
    # signal.  If transparency is now off, auto-derive a real active color for hooks
    # so the user still has a visible indicator (config keeps active_is_clone=True
    # so turning transparency back on restores the correct behavior).
    active_is_clone = config.get("active_is_clone", False)
    if active_is_clone and not tr.get("active"):
        from .colors import derive_palette
        palette_dirs  = derive_palette(hex_to_srgb(waiting_colors["bg"]))
        active_colors = derive_state_colors(palette_dirs["B"]["active"], fg_base, selbg_base)

    # Full-screen fallback for active state (only matters when transparency is on).
    # For clone-waiting (active bg == waiting bg), derive a blue so full-screen mode
    # shows something visible.  For distinct colors, the shift itself is the signal.
    fullscreen_active = config.get("fullscreen_active_colors")
    if fullscreen_active is None and active_alpha is not None:
        if active_colors.get("bg") == waiting_colors.get("bg"):
            from .colors import derive_palette
            palette_dirs = derive_palette(hex_to_srgb(waiting_colors["bg"]))
            fullscreen_active = derive_state_colors(
                palette_dirs["B"]["active"], fg_base, selbg_base
            )
        else:
            fullscreen_active = active_colors

    # Auto-expire blocked state (0 = disabled)
    blocked_expire  = config.get("blocked_expire",  0)
    blocked_enabled = config.get("blocked_enabled", True)

    # Pause / idle state
    pause_colors  = config.get("pause_colors")
    pause_timeout = config.get("pause_timeout", 3600)
    pause_idle_cmd  = _pause_idle_start(pause_colors, pause_timeout) if (pause_colors and pause_timeout) else ""
    use_idle_cancel = bool(pause_colors and pause_timeout)

    hook_commands = {
        "UserPromptSubmit": _active_cmd(
            active_colors, active_alpha, fullscreen_active,
            reset_stop=True, event_name="Submit", cancel_idle=use_idle_cancel,
        ),
        "PreToolUse": _active_cmd(
            active_colors, active_alpha, fullscreen_active,
            event_name="PreTool",
        ),
        "Stop": _restore_cmd(waiting_colors, waiting_alpha, pause_idle_cmd=pause_idle_cmd),
    }
    if blocked_enabled:
        hook_commands["Notification"] = _blocked_cmd(
            blocked_colors, waiting_colors, expire=blocked_expire, waiting_alpha=waiting_alpha
        )

    settings = _load_settings()
    hooks    = settings.setdefault("hooks", {})

    # If blocked is disabled, remove any existing Mondrian Notification hook.
    if not blocked_enabled:
        if "Notification" in hooks:
            hooks["Notification"] = [
                e for e in hooks["Notification"]
                if MONDRIAN_MARKER not in e.get("hooks", [{}])[0].get("command", "")
            ]
            if not hooks["Notification"]:
                del hooks["Notification"]

    for event, command in hook_commands.items():
        entries = hooks.setdefault(event, [])
        entries[:] = [
            e for e in entries
            if MONDRIAN_MARKER not in e.get("hooks", [{}])[0].get("command", "")
        ]
        entries.append(_make_hook_entry(command))

    _save_settings(settings)
    _write_restore_seq(waiting_colors)


def uninstall_hooks() -> None:
    if not SETTINGS_PATH.exists():
        return
    settings = _load_settings()
    hooks    = settings.get("hooks", {})

    for event in list(hooks.keys()):
        hooks[event] = [
            e for e in hooks[event]
            if MONDRIAN_MARKER not in e.get("hooks", [{}])[0].get("command", "")
        ]
        if not hooks[event]:
            del hooks[event]

    if not hooks:
        settings.pop("hooks", None)

    _save_settings(settings)


def hooks_installed() -> bool:
    settings = _load_settings()
    hooks    = settings.get("hooks", {})
    return any(
        MONDRIAN_MARKER in e.get("hooks", [{}])[0].get("command", "")
        for entries in hooks.values()
        for e in entries
    )
