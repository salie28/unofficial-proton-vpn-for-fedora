"""
The Recents list.

PLAN.md §5: Recents does not exist on Linux, so this is ours end to end - our
store (`recents.py`), our widget. Clicking a row calls Proton's controller to
connect, exactly like their own server rows do.
"""

from gi.repository import Gtk, Pango

from proton.vpn import logging

from ..futures import report_failure

from ..recents import RecentsStore

logger = logging.getLogger(__name__)


class RecentsView(Gtk.ScrolledWindow):
    """A list of recently used servers, most recent first."""

    #: Shown in the window; the tray shows fewer (PLAN.md §6). More than a
    #: handful stops being "recent" and starts being a second server list.
    MAX_ROWS = 8

    def __init__(self, controller, recents: RecentsStore = None):
        super().__init__()
        self._controller = controller
        self._recents = recents if recents is not None else RecentsStore()

        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_vexpand(True)
        self.add_css_class("recents-view")

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class("recents-list")
        self.set_child(self._list)

        self._empty_label = None
        self.refresh()

    def refresh(self):
        """Rebuild the rows, re-reading the file the tray writes to."""
        self._recents.reload()
        child = self._list.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self._list.remove(child)
            child = next_child

        servers = self._recents.most_recent(self.MAX_ROWS)
        if not servers:
            self._list.append(self._build_empty_row())
            return

        for server in servers:
            self._list.append(self._build_row(server))

    def _build_empty_row(self) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        label = Gtk.Label(label="No recent servers yet")
        label.add_css_class("recents-empty")
        label.set_margin_top(24)
        label.set_margin_bottom(24)
        row.set_child(label)
        return row

    def _build_row(self, server) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("recents-row")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)

        title = Gtk.Label(label=server.city or server.exit_country or server.server_name)
        title.set_xalign(0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class("recents-row-title")
        text.append(title)

        subtitle_text = server.server_name
        if server.is_secure_core:
            subtitle_text = f"{subtitle_text} · Secure Core"
        subtitle = Gtk.Label(label=subtitle_text)
        subtitle.set_xalign(0)
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle.add_css_class("recents-row-subtitle")
        text.append(subtitle)

        box.append(text)

        connect = Gtk.Button(label="Connect")
        connect.add_css_class("recents-connect")
        connect.set_valign(Gtk.Align.CENTER)
        connect.connect("clicked", self._on_connect_clicked, server.server_name)
        box.append(connect)

        row.set_child(box)
        return row

    def _on_connect_clicked(self, _button, server_name: str):
        """Connect through Proton's controller - never our own logic."""
        logger.info(f"Connect to {server_name}", category="ui.recents", event="connect")
        future = self._controller.connect_to_server(server_name)
        report_failure(future, f"Connecting to {server_name}")
