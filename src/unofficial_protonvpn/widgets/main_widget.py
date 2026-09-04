"""
Substituting our layout for Proton's.

`MainWindow` builds a `MainWidget`, and `MainWidget` builds a `VPNWidget`. We
want our own `VPNWidget` subclass in that last slot without touching either
file, so we do what the identity patch already does (PLAN.md §3): rebind a name
in their module, in our process only, before the class is looked up.

`MainWidget` keeps handling login, logout, session expiry and notifications -
PLAN.md §7 problem #4 - and only the post-login layout becomes ours.
"""

from proton.vpn import logging
from proton.vpn.app.gtk.utils.safe_signal_connect import safe_signal_connect
from proton.vpn.app.gtk.widgets.main.main_widget import MainWidget

from .main_layout import WindowsStyleVPNWidget

logger = logging.getLogger(__name__)


class WindowsStyleMainWidget(MainWidget):
    """Proton's main widget, building our VPN widget instead of theirs."""

    def _create_vpn_widget(self) -> WindowsStyleVPNWidget:
        # Mirrors MainWidget._create_vpn_widget, with our widget class.
        vpn_widget = WindowsStyleVPNWidget(
            controller=self._controller,
            main_window=self._main_window,
            notifications=self.notifications,
        )
        safe_signal_connect(
            vpn_widget, "vpn-widget-ready", self._hide_overlay_widget
        )
        signal_id = safe_signal_connect(
            vpn_widget,
            "connection-state-changed",
            self._change_gradient_on_connection_state_change
        )
        self._connected_signals.append((signal_id, vpn_widget))

        return vpn_widget


def install() -> bool:
    """Make `MainWindow` build our main widget. Call before creating a window.

    Returns whether the substitution took. A False here means the window falls
    back to Proton's own layout, which is a working app - not a broken one.
    """
    try:
        from proton.vpn.app.gtk.widgets.main import main_window
    except ImportError:
        logger.exception("Could not import main_window to install our layout.")
        return False

    if not hasattr(main_window, "MainWidget"):
        logger.warning(
            "proton.vpn.app.gtk.widgets.main.main_window no longer references "
            "MainWidget; keeping Proton's layout."
        )
        return False

    main_window.MainWidget = WindowsStyleMainWidget
    logger.info("Windows-style layout installed.")
    return True
