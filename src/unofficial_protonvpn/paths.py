"""
Where our own files live.

PLAN.md §2: "Read-only on everything Proton owns. Never write `site-packages`;
never write their `~/.config/Proton/VPN/settings.json`. Our settings go in our
own file." Every path this app writes to comes from here, so that rule is
enforceable by reading one short module.
"""

import os
from pathlib import Path

APP_DIRNAME = "unofficial-protonvpn"

#: Proton's own config directory. Listed so it is obvious what we must not write.
#: Proton's own config. Named here only so it is obvious what we must never
#: write to (PLAN.md §2). Nothing in this app opens it.
PROTON_CONFIG_DIR = Path.home() / ".config" / "Proton" / "VPN"


def config_dir() -> Path:
    """Our config directory, created on demand with private permissions."""
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    path = Path(base) / APP_DIRNAME
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def recents_file() -> Path:
    """Our recents store. Never Proton's settings.json."""
    return config_dir() / "recents.json"
