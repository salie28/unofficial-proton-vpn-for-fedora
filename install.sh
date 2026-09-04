#!/usr/bin/env bash
# Installs Unofficial Proton VPN for the current user.
#
# No root. Ever. (PLAN.md §2) This writes exactly two files under ~/.local and
# touches nothing that Proton owns. Uninstall = ./uninstall.sh, or delete them.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$REPO_DIR/src"

if [[ $EUID -eq 0 ]]; then
    echo "Do not run this as root. It installs into your home directory only." >&2
    exit 1
fi

# Identity comes from branding.py so the .desktop filename can never drift
# from the app ID (a mismatch makes GNOME label our window "Proton VPN").
read_branding() {
    PYTHONPATH="$SRC_DIR" python3 -c "from unofficial_protonvpn.branding import $1; print($1)"
}

APP_ID="$(read_branding APP_ID)"
APP_NAME="$(read_branding APP_NAME)"
APP_SUMMARY="$(read_branding APP_SUMMARY)"

# Refuse to install on top of Proton's own identity.
if [[ "$APP_ID" == "proton.vpn.app.gtk" ]]; then
    echo "APP_ID must not be Proton's own application ID." >&2
    exit 1
fi

echo "Checking prerequisites..."
if ! python3 -c "import proton.vpn.app.gtk" 2>/dev/null; then
    cat >&2 <<'MSG'
The official Proton VPN app is not installed, and this app builds on it.

Install it first:
    sudo dnf install proton-vpn-gnome-desktop

MSG
    exit 1
fi
UPSTREAM="$(python3 -c "from importlib.metadata import version; print(version('proton-vpn-gtk-app'))" 2>/dev/null || echo unknown)"
echo "  found proton-vpn-gtk-app $UPSTREAM"

DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"

# Remove any earlier install of *this* app under a different app ID. Changing
# GITHUB_HANDLE changes the ID, and without this the old .desktop and icons stay
# behind and the app appears twice in the launcher. Only ever matches our own
# naming pattern - nothing else is touched.
for stale in "$DESKTOP_DIR"/io.github.*.UnofficialProtonVPN.desktop; do
    [[ -e "$stale" ]] || continue
    stale_id="$(basename "$stale" .desktop)"
    [[ "$stale_id" == "$APP_ID" ]] && continue
    echo "  removing previous install: $stale_id"
    rm -f "$stale"
    for size in 16 24 32 48 64 128 256 512; do
        # Both the app icon and the tray's disconnected variant.
        rm -f "$HOME/.local/share/icons/hicolor/${size}x${size}/apps/$stale_id.png" \
              "$HOME/.local/share/icons/hicolor/${size}x${size}/apps/$stale_id-disconnected.png"
    done
done

ICON_SRC="$SRC_DIR/unofficial_protonvpn/assets/icons"
for size in 16 24 32 48 64 128 256 512; do
    dir="$HOME/.local/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$dir"
    install -m 0644 "$ICON_SRC/app-icon-${size}.png" "$dir/$APP_ID.png"
    # Grey variant: the tray shows this when the tunnel is down.
    install -m 0644 "$ICON_SRC/app-icon-disconnected-${size}.png" \
        "$dir/$APP_ID-disconnected.png"
done
echo "  icons   -> ~/.local/share/icons/hicolor/*/apps/$APP_ID{,-disconnected}.png"

sed -e "s|@APP_NAME@|$APP_NAME|g" \
    -e "s|@APP_SUMMARY@|$APP_SUMMARY|g" \
    -e "s|@APP_ID@|$APP_ID|g" \
    -e "s|@SRC_DIR@|$SRC_DIR|g" \
    "$REPO_DIR/data/app.desktop.in" > "$DESKTOP_DIR/$APP_ID.desktop"
chmod 0644 "$DESKTOP_DIR/$APP_ID.desktop"
echo "  desktop -> $DESKTOP_DIR/$APP_ID.desktop"

# Refresh caches so it shows up without a re-login. Both are optional.
command -v update-desktop-database >/dev/null && update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache   >/dev/null && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

cat <<MSG

Installed. Search your applications for "$APP_NAME" (or type "proton").

Note: this app requires a PAID Proton VPN plan, and is unofficial - not
affiliated with, endorsed by, or produced by Proton AG.
MSG
