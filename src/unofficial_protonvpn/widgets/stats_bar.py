"""
The bottom stats bar.

PLAN.md §4: "VPN IP, server load, protocol, total traffic, and up/down rates.
Plain text on a 1-second poll - no graph" (§8: "No graph step. Explicitly
cut.").

PLAN.md §7 problem #2 is the one way this app could actually harm someone: the
UI claiming a connection that is not there. So every field here is cleared the
moment the state stops being Connected, and the traffic figures come from the
interface itself - if `proton0` is gone, they read as disconnected no matter
what any widget believes.
"""

from typing import Optional

from gi.repository import GLib, Gtk

from proton.vpn import logging

from ..protocols import protocol_name
from ..traffic import TrafficMeter, format_bytes, format_rate
from .traffic_graph import TrafficGraph

logger = logging.getLogger(__name__)

PLACEHOLDER = "-"


class ServerLoadBar(Gtk.DrawingArea):
    """A small bar showing how loaded the server is.

    Green below half, amber to three quarters, red above - the same reading
    their server-load widget gives.
    """

    WIDTH = 34
    HEIGHT = 4

    LOW = (0.294, 0.725, 0.616)      # #4BB99D
    MEDIUM = (1.0, 0.678, 0.2)       # #FFAD33
    HIGH = (0.969, 0.376, 0.482)     # #F7607B

    def __init__(self):
        super().__init__()
        self.add_css_class("server-load-bar")
        self.set_content_width(self.WIDTH)
        self.set_content_height(self.HEIGHT)
        self.set_valign(Gtk.Align.CENTER)
        self.set_can_target(False)
        self._load = None          # what is drawn right now
        self._target = None        # where it is heading
        self._tick_id = None
        self.set_draw_func(self._draw)

    #: Seconds the bar takes to reach a new value.
    EASE_SECONDS = 0.45

    def set_load(self, fraction) -> None:
        """Set the load as 0..1, or None to show nothing.

        The bar slides to the new value rather than jumping: server load is
        polled every second and a bar that snaps looks like a glitch.
        """
        self._target = fraction

        if fraction is None or self._load is None:
            # Nothing to ease between - appear or disappear outright.
            self._load = fraction
            self.queue_draw()
            return

        if self._tick_id is None:
            self._start = None
            self._from = self._load
            self._tick_id = self.add_tick_callback(self._on_tick)
        else:
            self._from = self._load
            self._start = None

    def _on_tick(self, _widget, frame_clock) -> bool:
        if self._target is None:
            self._tick_id = None
            return False

        now = frame_clock.get_frame_time() / 1_000_000.0
        if self._start is None:
            self._start = now

        progress = min((now - self._start) / self.EASE_SECONDS, 1.0)
        eased = 1.0 - (1.0 - progress) ** 3
        self._load = self._from + (self._target - self._from) * eased
        self.queue_draw()

        if progress >= 1.0:
            self._load = self._target
            self._tick_id = None
            return False
        return True

    def _colour(self):
        if self._load is None:
            return self.LOW
        if self._load < 0.5:
            return self.LOW
        if self._load < 0.75:
            return self.MEDIUM
        return self.HIGH

    def _draw(self, _area, context, width, height):
        radius = height / 2
        context.set_source_rgba(1, 1, 1, 0.12)
        context.rectangle(0, 0, width, height)
        context.fill()

        if not self._load:
            return

        context.set_source_rgb(*self._colour())
        context.rectangle(0, 0, max(width * self._load, radius), height)
        context.fill()


class StatsBar(Gtk.Box):
    """A row of plain-text connection figures."""

    POLL_INTERVAL_SECONDS = 1

    def __init__(self, controller, meter: Optional[TrafficMeter] = None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=28)
        self._controller = controller
        self._meter = meter if meter is not None else TrafficMeter()
        self._poll_source_id = None
        self._device_ip = None
        self._server_name = None
        self._protocol_name = None
        self._connected = False

        self.add_css_class("stats-bar")
        self.set_hexpand(True)
        for setter in (self.set_margin_start, self.set_margin_end):
            setter(16)
        self.set_margin_top(6)
        self.set_margin_bottom(4)

        # Laid out like the Windows app: the figures in a compact block on
        # the left, the live chart and its rates on the right. A single row of
        # seven equal cells overflowed the window and clipped the chart.
        self._cells = {}

        figures = Gtk.Grid()
        # Centred against the chart: the chart is taller than the two rows of
        # figures, so aligning them to the top leaves them floating.
        figures.set_valign(Gtk.Align.CENTER)
        figures.set_row_spacing(6)
        figures.set_column_spacing(22)
        figures.add_css_class("stats-figures")
        for column, row, key, caption in (
            (0, 0, "ip", "VPN IP"),
            (1, 0, "load", "Server load"),
            (0, 1, "protocol", "Protocol"),
            (1, 1, "total", "Total traffic"),
        ):
            cell, value = self._build_cell(caption)
            cell.set_size_request(118, -1)
            self._cells[key] = value
            if key == "load":
                # Their server-load cell carries a bar beside the percentage.
                self.load_bar = ServerLoadBar()
                row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                cell.remove(value)
                row_box.append(value)
                row_box.append(self.load_bar)
                cell.append(row_box)
            figures.attach(cell, column, row, 1, 1)
        self.append(figures)

        self.append(self._build_graph_cell())

        self.clear()

    def _build_cell(self, caption: str):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.add_css_class("stats-cell")
        box.set_hexpand(True)
        box.set_size_request(96, -1)

        caption_label = Gtk.Label(label=caption)
        caption_label.set_xalign(0)
        caption_label.add_css_class("stats-caption")

        value_label = Gtk.Label(label=PLACEHOLDER)
        value_label.set_xalign(0)
        value_label.add_css_class("stats-value")
        # Selectable so the IP can be copied, but not focusable: an empty
        # selectable label grabs focus on start and renders as a stray caret
        # block in the corner of the bar.
        value_label.set_selectable(True)
        value_label.set_can_focus(False)
        value_label.set_focus_on_click(False)

        box.append(caption_label)
        box.append(value_label)
        return box, value_label

    def _build_graph_cell(self) -> Gtk.Widget:
        """The chart, with the live rates above it."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("stats-cell")
        box.set_hexpand(True)
        box.set_valign(Gtk.Align.CENTER)
        box.set_size_request(420, -1)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        caption = Gtk.Label(label="Current traffic")
        caption.set_xalign(0)
        caption.set_hexpand(True)
        caption.add_css_class("stats-caption")
        header.append(caption)

        for key in ("down", "up"):
            label = Gtk.Label(label=PLACEHOLDER)
            label.add_css_class("stats-rate")
            label.add_css_class(f"stats-rate-{key}")
            self._cells[key] = label
            header.append(label)

        box.append(header)

        self.graph = TrafficGraph()
        box.append(self.graph)
        return box

    # -- state ------------------------------------------------------------

    def status_update(self, state):
        """Follow the connection state.

        Called from the connection state machine's thread, not the GTK main
        thread - the same contract Proton's own `VPNWidget.status_update`
        follows. Everything below touches widgets or the controller, so it is
        handed to the main loop rather than run here. Doing the work inline
        deadlocks: `Controller.get_settings()` submits to the executor and
        blocks on the result, and this callback is running on that executor.
        """
        GLib.idle_add(self._apply_state, state)

    def _apply_state(self, state) -> bool:
        """Runs on the GTK main thread."""
        try:
            if type(state).__name__ != "Connected":
                self._connected = False
                self.clear()
                self._stop_poll()
                return GLib.SOURCE_REMOVE

            self._connected = True
            self._device_ip = self._extract_device_ip(state) or self._device_ip
            connection = getattr(getattr(state, "context", None), "connection", None)
            self._server_name = getattr(connection, "server_name", None)
            self._protocol_name = self._protocol_from(connection)

            self._refresh_static_fields()
            self._start_poll()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Stats bar could not follow the connection state.")
            self.clear()
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _extract_device_ip(state) -> Optional[str]:
        """Our apparent public IP, reported by the local agent."""
        event = getattr(getattr(state, "context", None), "event", None)
        details = getattr(getattr(event, "context", None), "connection_details", None)
        return getattr(details, "device_ip", None)

    def _clear_traffic(self) -> None:
        """Blank only the figures that come from the interface counters."""
        for key in ("down", "up", "total"):
            self._cells[key].set_text(PLACEHOLDER)
        self.graph.clear()

    def clear(self):
        """Show nothing rather than something stale (PLAN.md §7 #2)."""
        for label in self._cells.values():
            label.set_text(PLACEHOLDER)
        self.graph.clear()
        if hasattr(self, "load_bar"):
            self.load_bar.set_load(None)

    def _refresh_static_fields(self):
        self._cells["ip"].set_text(self._device_ip or PLACEHOLDER)
        self._cells["protocol"].set_text(self._protocol())
        self._cells["load"].set_text(self._server_load())
        self.load_bar.set_load(self._load_fraction())

    @staticmethod
    def _protocol_from(connection) -> Optional[str]:
        """The protocol of the live connection.

        Taken from the connection object rather than
        `Controller.get_settings()`, which blocks on the executor: the settings
        value is also only what the *next* connection would use, not what this
        one is actually running.
        """
        protocol = getattr(connection, "protocol", None)
        return str(protocol) if protocol else None

    def _protocol(self) -> str:
        return protocol_name(self._protocol_name) or PLACEHOLDER

    def _load_fraction(self):
        """Server load as 0..1, or None when unknown."""
        if not self._server_name:
            return None
        try:
            logical = self._controller.server_list.get_by_name(self._server_name)
            load = getattr(logical, "load", None)
            return None if load is None else max(0.0, min(float(load) / 100.0, 1.0))
        except Exception:  # pylint: disable=broad-except
            return None

    def _server_load(self) -> str:
        if not self._server_name:
            return PLACEHOLDER
        try:
            logical = self._controller.server_list.get_by_name(self._server_name)
            load = getattr(logical, "load", None)
        except Exception:  # pylint: disable=broad-except
            return PLACEHOLDER
        return f"{int(load)}%" if load is not None else PLACEHOLDER

    # -- the 1 second poll -------------------------------------------------

    def _start_poll(self):
        if self._poll_source_id is not None:
            return
        self._meter.reset()
        self._poll_source_id = GLib.timeout_add_seconds(
            self.POLL_INTERVAL_SECONDS, self._on_tick)

    def _stop_poll(self):
        if self._poll_source_id is None:
            return
        GLib.source_remove(self._poll_source_id)
        self._poll_source_id = None
        self._meter.reset()

    def _on_tick(self) -> bool:
        try:
            sample = self._meter.sample()
            if not sample.connected:
                # No counters to read. That does NOT mean the VPN is down: the
                # tunnel's device depends on the protocol, and it can be absent
                # for a moment while a connection is being set up. Blank the
                # traffic figures only - the IP, protocol and load come from the
                # connection itself and are still true. Whether we are
                # protected is decided by the connection state, not by whether
                # a network device happens to be named what we expected.
                self._clear_traffic()
                return True

            self._cells["down"].set_text(f"\u2193 {format_rate(sample.down_rate)}")
            self._cells["up"].set_text(f"\u2191 {format_rate(sample.up_rate)}")
            self._cells["total"].set_text(format_bytes(sample.total))
            self.graph.push(sample.down_rate, sample.up_rate)
            # Load moves on its own; refresh it on the same tick.
            load = self._server_load()
            self._cells["load"].set_text(load)
            self.load_bar.set_load(self._load_fraction())
        except Exception:  # pylint: disable=broad-except
            logger.exception("Stats poll failed; stopping it.")
            self._poll_source_id = None
            return False
        return True

    def teardown(self):
        """Stop the poll. Call before the widget goes away."""
        self._stop_poll()
