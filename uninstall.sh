#!/usr/bin/env bash
# Removes the two files install.sh created. Nothing else exists to remove.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="$(PYTHONPATH="$REPO_DIR/src" python3 -c \
    "from unofficial_protonvpn.branding import APP_ID; print(APP_ID)")"

for size in 16 24 32 48 64 128 256 512; do
    dir="$HOME/.local/share/icons/hicolor/${size}x${size}/apps"
    rm -fv "$dir/$APP_ID.png" "$dir/$APP_ID-disconnected.png"
done
rm -fv "$HOME/.local/share/applications/$APP_ID.desktop"

command -v update-desktop-database >/dev/null && \
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "Removed. The official Proton VPN app was never touched."
