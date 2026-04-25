"""
Patch ~/.claude/settings.json to add / remove Mondrian iTerm2 hooks.
"""

import json
from pathlib import Path
from typing import Optional

SETTINGS_PATH = Path("~/.claude/settings.json").expanduser()
CONFIG_PATH   = Path("~/.mondrian.json").expanduser()

MONDRIAN_MARKER = "Mondrian"
STOP_TS_FILE    = "/tmp/.mondrian_stop"


# ---------------------------------------------------------------------------
# Low-level command builders
# ---------------------------------------------------------------------------

def _colors_seq(bg: str, fg: str, bold: str, selbg: str, selfg: str) -> str:
    b, f, bo, sb, sf = [c.lstrip("#") for c in (bg, fg, bold, selbg, selfg)]
    return f"\\033]1337;SetColors=bg={b},fg={f},bold={bo},selbg={sb},selfg={sf}\\007"


def _send_seq(seq: str) -> str:
    return f"printf '{seq}' > /dev/tty 2>/dev/null || printf '{seq}' >&2"


def _transparency_stmt(alpha: float) -> str:
    script = (
        f'tell application "iTerm2" to tell current session of '
        f'current window to set transparency to {alpha:.3f}'
    )
    return f"osascript -e '{script}' 2>/dev/null"


def _join(*parts: str) -> str:
    """Join shell statements and append the Mondrian marker."""
    return "; ".join(parts) + " # Mondrian"


# ---------------------------------------------------------------------------
# Per-event command builders
# ---------------------------------------------------------------------------

def _active_cmd(colors: dict, alpha: Optional[float] = None) -> str:
    parts = [_send_seq(_colors_seq(**colors))]
    if alpha is not None:
        parts.append(_transparency_stmt(alpha))
    return _join(*parts)


def _restore_cmd(colors: dict, alpha: Optional[float] = None) -> str:
    """Stop hook: stamp the time so Notification can detect end-of-response."""
    parts = [
        f"echo $(date +%s) > {STOP_TS_FILE}",
        _send_seq(_colors_seq(**colors)),
    ]
    if alpha is not None:
        parts.append(_transparency_stmt(alpha))
    return _join(*parts)


def _blocked_cmd(colors: dict, alpha: Optional[float] = None, grace: int = 3) -> str:
    """Notification hook: only show blocked if Stop fired >grace seconds ago.
    This filters out the spurious Notification that fires right after Stop
    at the end of normal responses."""
    seq  = _colors_seq(**colors)
    send = _send_seq(seq)
    inner_parts = [send]
    if alpha is not None:
        inner_parts.append(_transparency_stmt(alpha))
    inner = "; ".join(inner_parts)
    return (
        f"ts=$(cat {STOP_TS_FILE} 2>/dev/null||echo 0); "
        f"[ $(($(date +%s)-ts)) -gt {grace} ] && "
        f"{{ {inner}; }} # Mondrian"
    )


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

    hook_commands = {
        "UserPromptSubmit": _active_cmd(active_colors,  active_alpha),
        "Stop":             _restore_cmd(waiting_colors, waiting_alpha),
        "Notification":     _blocked_cmd(blocked_colors),  # color only, transparency unchanged
    }

    settings = _load_settings()
    hooks    = settings.setdefault("hooks", {})

    for event, command in hook_commands.items():
        entries = hooks.setdefault(event, [])
        entries[:] = [
            e for e in entries
            if MONDRIAN_MARKER not in e.get("hooks", [{}])[0].get("command", "")
        ]
        entries.append(_make_hook_entry(command))

    _save_settings(settings)


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
