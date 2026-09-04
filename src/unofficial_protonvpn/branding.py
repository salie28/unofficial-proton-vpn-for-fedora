"""
Single source of truth for this app's identity.

PLAN.md §1: "The name lives in three strings only: `Name=` in the `.desktop`,
the app ID, and the README title." They all derive from here, and `install.sh`
reads APP_ID from this file so the `.desktop` filename can never drift from it
(a mismatch makes GNOME label our window with Proton's name - PLAN.md §3).
"""

# Changing this is enough: the .desktop filename, the app ID and the icon name
# all follow.
GITHUB_HANDLE = "salie28"

APP_NAME = "Unofficial Proton VPN"
APP_ID = f"io.github.{GITHUB_HANDLE}.UnofficialProtonVPN"

# The icon file installed into ~/.local/share/icons/.../APP_ICON.svg.
# Freedesktop expects the icon name to match the app ID.
APP_ICON = APP_ID

APP_SUMMARY = "Unofficial Proton VPN client with a Windows-style layout"

# Upstream versions this has actually been tested against. A mismatch is a
# warning, never a hard stop: PLAN.md §7 problem #3 says their refactors break
# us hard, so we say so out loud rather than dying with a traceback.
TESTED_UPSTREAM_VERSIONS = ("4.18",)

#: The upstream major series this is built against. Nothing is pinned: the app
#: runs against whatever Proton version is installed, and says so if their
#: internals have moved. A different *major* series is worth warning about,
#: because that is where they are most likely to have rearranged things. A
#: newer minor release is not, or every routine Proton update would nag.
SUPPORTED_UPSTREAM_MAJOR = "4"
