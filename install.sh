#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "  mondrian install"
echo ""

# Check Python 3
if ! command -v python3 &>/dev/null; then
  echo "  ✗ python3 not found. Install it with: brew install python" >&2
  exit 1
fi

# Make the CLI executable and symlink to /usr/local/bin
chmod +x "$DIR/mondrian.py"
if [[ -w /usr/local/bin ]]; then
  ln -sf "$DIR/mondrian.py" /usr/local/bin/mondrian
  echo "  Linked mondrian → /usr/local/bin/mondrian"
else
  echo "  Note: /usr/local/bin not writable. Run manually with: python3 $DIR/mondrian.py"
fi

# Run configure
python3 "$DIR/mondrian.py" configure
