"""
Loads our stylesheet on top of Proton's.

PLAN.md §3: theirs loads at PRIORITY_APPLICATION (600) from
`assets/style/__init__.py`; ours loads at PRIORITY_USER (800) and wins, with no
upstream file edited. This is the whole styling mechanism.
"""

from importlib.resources import files

from gi.repository import Gdk, Gtk

from proton.vpn import logging

logger = logging.getLogger(__name__)

OVERLAY_CSS = "overlay.css"


def load_overlay_css(display: Gdk.Display = None) -> bool:
    """Add our CSS to `display` above Proton's. Returns True if it loaded.

    Styling is the one part of this app that degrades gracefully (PLAN.md §7
    problem #3), so a failure here logs and carries on with Proton's own look
    rather than taking the window down with it.
    """
    display = display or Gdk.Display.get_default()
    if display is None:
        logger.warning("No display available; skipping overlay CSS.")
        return False

    try:
        css_path = files(f"{__package__}.assets.style").joinpath(OVERLAY_CSS)
        provider = Gtk.CssProvider()
        provider.load_from_path(str(css_path))
    except Exception as error:  # pylint: disable=broad-except
        logger.warning(f"Could not load {OVERLAY_CSS}: {error}")
        return False

    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
    )
    logger.info(f"Loaded {OVERLAY_CSS} at PRIORITY_USER.")
    return True
