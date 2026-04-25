"""
Shell precmd / PROMPT_COMMAND hook for focus-based restore of the waiting state.

When installed, fires before every shell prompt. If /tmp/.mondrian_blocked
exists (set by the Notification hook), sources ~/.mondrian/restore_seq.sh
which sends the waiting-state SetColors and removes the marker file.
"""

from pathlib import Path

_BEGIN = "# mondrian shell hook begin"
_END   = "# mondrian shell hook end"

RESTORE_SEQ_PATH = Path("~/.mondrian/restore_seq.sh").expanduser()

_RC_CANDIDATES = [
    Path("~/.zshrc").expanduser(),
    Path("~/.bashrc").expanduser(),
    Path("~/.bash_profile").expanduser(),
]

# Shell-agnostic snippet: works in both zsh (precmd_functions) and bash (PROMPT_COMMAND)
_SNIPPET = (
    f"\n{_BEGIN}\n"
    "_mondrian_focus_restore() {\n"
    "  [ -f /tmp/.mondrian_blocked ]"
    " && . ~/.mondrian/restore_seq.sh 2>/dev/null\n"
    "}\n"
    'if [ -n "$ZSH_VERSION" ]; then\n'
    "  precmd_functions+=(_mondrian_focus_restore)\n"
    'elif [ -n "$BASH_VERSION" ]; then\n'
    '  PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND; }_mondrian_focus_restore"\n'
    "fi\n"
    f"{_END}\n"
)


def shell_hook_installed() -> bool:
    return any(
        rc.exists() and _BEGIN in rc.read_text()
        for rc in _RC_CANDIDATES
    )


def default_rc() -> Path:
    """Return ~/.zshrc if it exists, else ~/.bashrc."""
    zshrc = Path("~/.zshrc").expanduser()
    return zshrc if zshrc.exists() else Path("~/.bashrc").expanduser()


def install_shell_hook(rc_path: Path | None = None) -> Path:
    """Append the precmd snippet to rc_path (default: auto-detected rc file)."""
    if rc_path is None:
        rc_path = default_rc()

    text = rc_path.read_text() if rc_path.exists() else ""
    if _BEGIN in text:
        return rc_path  # already present

    with open(rc_path, "a") as f:
        f.write(_SNIPPET)

    return rc_path


def remove_shell_hook() -> list[Path]:
    """Remove the mondrian snippet from all known rc files. Returns modified paths."""
    modified = []
    for rc in _RC_CANDIDATES:
        if not rc.exists():
            continue
        text = rc.read_text()
        if _BEGIN not in text:
            continue

        lines  = text.splitlines(keepends=True)
        out    = []
        inside = False
        for line in lines:
            if _BEGIN in line:
                inside = True
            if not inside:
                out.append(line)
            if _END in line:
                inside = False

        rc.write_text("".join(out).rstrip("\n") + "\n")
        modified.append(rc)

    return modified
