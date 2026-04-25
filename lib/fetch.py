"""
Remote scheme fetching and local library management.

Schemes are sourced from mbadolato/iTerm2-Color-Schemes (GitHub) and stored
in ~/.mondrian/schemes/ as plain .itermcolors files.
"""

import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

SCHEMES_DIR  = Path("~/.mondrian/schemes").expanduser()
_REMOTE_BASE = "https://raw.githubusercontent.com/mbadolato/iTerm2-Color-Schemes/master/schemes/"
_REMOTE_API  = "https://api.github.com/repos/mbadolato/iTerm2-Color-Schemes/contents/schemes"


def ensure_schemes_dir() -> Path:
    SCHEMES_DIR.mkdir(parents=True, exist_ok=True)
    return SCHEMES_DIR


def list_remote_schemes() -> list[str]:
    """Return sorted scheme names available in the upstream repo."""
    with urllib.request.urlopen(_REMOTE_API, timeout=15) as r:
        data = json.loads(r.read())
    return sorted(
        (item["name"].removesuffix(".itermcolors") for item in data
         if item["name"].endswith(".itermcolors")),
        key=str.lower,
    )


def fetch_scheme(name: str) -> Path:
    """Download a single scheme by name into SCHEMES_DIR. Returns the saved path."""
    ensure_schemes_dir()
    url  = _REMOTE_BASE + urllib.parse.quote(name + ".itermcolors")
    dest = SCHEMES_DIR / f"{name}.itermcolors"
    urllib.request.urlretrieve(url, dest)
    return dest


def fetch_all_schemes(on_progress=None) -> tuple[int, int]:
    """
    Download every scheme in the upstream repo.
    on_progress(i, total, name) is called before each fetch.
    Returns (succeeded, total).
    """
    names = list_remote_schemes()
    ensure_schemes_dir()
    ok = 0
    for i, name in enumerate(names, 1):
        if on_progress:
            on_progress(i, len(names), name)
        try:
            fetch_scheme(name)
            ok += 1
        except Exception:
            pass
    return ok, len(names)


def copy_to_library(src_path: str) -> Path:
    """Copy a .itermcolors file into SCHEMES_DIR. Returns destination path."""
    ensure_schemes_dir()
    dest = SCHEMES_DIR / Path(src_path).name
    shutil.copy2(src_path, dest)
    return dest


def list_local_schemes() -> list[tuple[str, str]]:
    """Return sorted [(name, path)] for all schemes in SCHEMES_DIR."""
    if not SCHEMES_DIR.exists():
        return []
    return sorted(
        ((f.stem, str(f)) for f in SCHEMES_DIR.glob("*.itermcolors")),
        key=lambda x: x[0].lower(),
    )
