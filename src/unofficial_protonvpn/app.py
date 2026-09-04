"""
Our Gtk.Application.

Proton's `App` with our identity, our stylesheet and our tray menu layered on
top. Steps 4-7 of PLAN.md replace the window contents; until then the window is
theirs and the tray is ours.

Never import this module before `identity.claim_application_id()` has run: it
pulls in `proton.vpn.app.gtk.app`, which binds APPLICATION_ID at import time.
"""

from gi.repository import Gdk

from proton.vpn import logging
from proton.vpn.app.gtk.app import App as ProtonApp
from proton.vpn.app.gtk.widgets.main.tray_indicator import TrayIndicatorNotSupported

from .branding import APP_ID, APP_ICON, APP_NAME
from .style import load_overlay_css
from .widgets.main_widget import install as install_layout
from .tray import QuickAccessTrayIndicator

logger = logging.getLogger(__name__)


class UnofficialProtonVPNApp(ProtonApp):
    """Proton's application, wearing our identity, our CSS and our tray."""

    def do_startup(self):  # pylint: disable=arguments-differ
        # Their startup loads Proton's main.css at PRIORITY_APPLICATION (600).
        ProtonApp.do_startup(self)
        # Ours goes on top at PRIORITY_USER (800). See PLAN.md §3.
        load_overlay_css(Gdk.Display.get_default())
        logger.info(f"Started as {APP_ID}", category="APP", event="PROCESS_START")

    def do_activate(self):  # pylint: disable=arguments-differ
        # Must happen before MainWindow is constructed: it looks MainWidget up
        # from its own module at call time.
        if self.window is None:
            install_layout()

        ProtonApp.do_activate(self)
        # The icon name must match the .desktop / app ID or the shell falls back
        # to Proton's icon in the window list.
        if self.window is not None:
            self._resize_for_three_columns(self.window)
            # MainWindow hardcodes set_title("Proton VPN"); ours must not claim
            # to be their app.
            self.window.set_title(APP_NAME)
            self.window.set_icon_name(APP_ICON)
            self.window.add_css_class("unofficial-protonvpn")

    #: The stock window is a single narrow column, fixed at that size. Ours has
    #: a sidebar, a connection panel and an action rail side by side.
    WINDOW_WIDTH = 1180
    WINDOW_HEIGHT = 780
    MIN_WINDOW_WIDTH = 900
    MIN_WINDOW_HEIGHT = 600

    @classmethod
    def _resize_for_three_columns(cls, window):
        """Give the window room for our layout, and let the user resize it.

        `MainWindow._configure_window` calls `set_resizable(False)` and pins a
        single-column size. Three columns do not fit in that, which is what
        makes the panels overlap.
        """
        window.set_resizable(True)
        window.set_size_request(cls.MIN_WINDOW_WIDTH, cls.MIN_WINDOW_HEIGHT)
        window.set_default_size(cls.WINDOW_WIDTH, cls.WINDOW_HEIGHT)

    @property
    def tray_indicator(self):
        """Our quick-access tray menu instead of the stock one (PLAN.md §6).

        Mirrors Proton's own property, including its "tray is optional" contract:
        if the desktop has no tray support, the app carries on without one.
        """
        if self._tray_indicator:
            return self._tray_indicator

        try:
            tray_indicator = QuickAccessTrayIndicator(self._controller)
            tray_indicator.setup(self.window)
        except TrayIndicatorNotSupported as error:
            logger.warning(str(error))
        else:
            self._tray_indicator = tray_indicator

        return self._tray_indicator

    def do_shutdown(self):  # pylint: disable=arguments-differ
        """Stop our 1 second traffic poll before GTK tears the app down."""
        indicator = self._tray_indicator
        if indicator is not None and hasattr(indicator, "teardown"):
            try:
                indicator.teardown()
            except Exception:  # pylint: disable=broad-except
                logger.exception("Tray teardown failed.")

        shutdown = getattr(ProtonApp, "do_shutdown", None)
        if shutdown is not None:
            shutdown(self)
