#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "$DIR/mondrian.py" uninstall

# Remove symlink if present
if [[ -L /usr/local/bin/mondrian ]]; then
  rm /usr/local/bin/mondrian
  echo "  Removed /usr/local/bin/mondrian"
fi
