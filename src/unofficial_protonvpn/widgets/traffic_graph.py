"""
The traffic graph.

The Windows app shows recent throughput as a small live chart beside the
figures, and that is what this draws: the last minute of download and upload
rates, fed by the same one-second poll as the rest of the stats bar.

PLAN.md cut a graph ("No graph step. Explicitly cut."). That was the right call
at the time - it kept the estimate honest - and this is a deliberate change of
mind, asked for after seeing the layout working.

Nothing here reads the network on its own: it is handed samples that already
came from `/sys/class/net/proton0/statistics`, so when the tunnel is gone the
graph empties like everything else.
"""

from collections import deque
from typing import Deque, Tuple

from gi.repository import Gtk

#: One sample per second, so this is a minute of history.
HISTORY = 60

#: Never scale below this, or idle noise looks like heavy traffic.
MINIMUM_SCALE_BYTES = 64 * 1024  # 64 KB/s

#: Headroom above the peak, as the Windows client uses.
Y_AXIS_BUFFER = 1.1


def _round_up_to_step(value: float) -> float:
    """Round up to a readable axis maximum, their step ladder."""
    import math

    if value <= 0:
        return 10.0
    magnitude = 10 ** math.floor(math.log10(value))
    return math.ceil(value / magnitude) * magnitude


class TrafficGraph(Gtk.DrawingArea):
    """A small live chart of download and upload rates."""

    # From the Windows client: download is SignalSuccess and drawn solid,
    # upload is SignalDanger and dashed 3,3. Download is drawn on top.
    DOWNLOAD_COLOUR = (0.294, 0.725, 0.616)   # #4BB99D
    UPLOAD_COLOUR = (0.969, 0.376, 0.482)     # #F7607B
    AXIS_COLOUR = (1, 1, 1, 0.07)
    BASELINE_COLOUR = (1, 1, 1, 0.16)

    #: Seconds a new sample takes to slide in. Matches the poll interval, so
    #: the line flows continuously instead of stepping once a second.
    ENTRY_SECONDS = 0.8

    def __init__(self, history: int = HISTORY):
        super().__init__()
        self.add_css_class("traffic-graph")
        #: Their chart is 70px tall.
        self.set_content_height(88)
        self.set_hexpand(True)
        self.set_can_target(False)
        self.set_can_focus(False)

        self._history = history
        self._samples: Deque[Tuple[float, float]] = deque(maxlen=history)
        #: 0..1 while the newest sample slides in from the right.
        self._entry = 1.0
        self._entry_start = None
        self._tick_id = None
        self.set_draw_func(self._draw)

    # -- data --------------------------------------------------------------

    def push(self, down_rate: float, up_rate: float) -> None:
        """Add one second of data, sliding it in rather than jumping."""
        self._samples.append((max(down_rate, 0.0), max(up_rate, 0.0)))
        self._entry = 0.0
        self._entry_start = None
        if self._tick_id is None:
            self._tick_id = self.add_tick_callback(self._on_tick)
        self.queue_draw()

    def _on_tick(self, _widget, frame_clock) -> bool:
        now = frame_clock.get_frame_time() / 1_000_000.0
        if self._entry_start is None:
            self._entry_start = now

        self._entry = min((now - self._entry_start) / self.ENTRY_SECONDS, 1.0)
        self.queue_draw()

        if self._entry >= 1.0:
            self._tick_id = None
            return False
        return True

    def clear(self) -> None:
        """Forget everything. Called when the tunnel goes away."""
        self._samples.clear()
        self._entry = 1.0
        self._entry_start = None
        self.queue_draw()

    @property
    def samples(self):
        """The stored history, oldest first."""
        return list(self._samples)

    def scale(self) -> float:
        """Bytes/second at the top of the chart.

        Follows the Windows client: take the peak of both series, add a 10%
        buffer, then round up to a readable step so the axis does not jitter
        with every sample.
        """
        peak = 0.0
        for down, up in self._samples:
            peak = max(peak, down, up)
        peak = max(peak * Y_AXIS_BUFFER, MINIMUM_SCALE_BYTES)
        return _round_up_to_step(peak)

    # -- drawing -----------------------------------------------------------

    def _draw(self, _area, context, width, height):
        if width <= 0 or height <= 0:
            return

        context.set_line_width(1.0)

        # Zero is the bottom of the chart and is drawn as a solid baseline; the
        # lines above it are faint and dashed so they cannot be mistaken for it.
        baseline = height - 0.5
        context.set_source_rgba(*self.BASELINE_COLOUR)
        context.move_to(0, baseline)
        context.line_to(width, baseline)
        context.stroke()

        context.set_source_rgba(*self.AXIS_COLOUR)
        context.set_dash([2.0, 4.0])
        for fraction in (0.5, 1.0):
            y = baseline - fraction * (height - 3)
            context.move_to(0, y)
            context.line_to(width, y)
            context.stroke()
        context.set_dash([])

        if len(self._samples) < 2:
            return

        scale = self.scale()
        # Upload first, download over it - their z-order.
        self._plot(context, width, height, scale, index=1,
                   colour=self.UPLOAD_COLOUR, dash=[3.0, 3.0])
        self._plot(context, width, height, scale, index=0,
                   colour=self.DOWNLOAD_COLOUR, dash=None)

    def points_for(self, width, height, scale, index):
        """Screen positions for one series, oldest first.

        Split out from drawing so it can be tested: a silent mistake in here
        renders as a chart that twitches, which no test would otherwise catch.
        """
        samples = list(self._samples)
        if not samples:
            return []

        step = width / max(self._history - 1, 1)
        first_x = width - (len(samples) - 1) * step
        last = len(samples) - 1

        points = []
        for position, sample in enumerate(samples):
            value = sample[index]
            # Ease the newest sample up from its predecessor as it arrives,
            # so the line grows into place instead of stepping once a second.
            if position == last and last > 0:
                previous = samples[position - 1][index]
                value = previous + (value - previous) * self._entry
            x = first_x + position * step
            y = (height - 1) - (value / scale) * (height - 4)
            points.append((x, y))
        return points

    def _plot(self, context, width, height, scale, index, colour, dash=None):
        """Draw one series as a filled line."""
        points = self.points_for(width, height, scale, index)
        if len(points) < 2:
            return

        context.set_source_rgba(*colour, 0.14)
        context.move_to(points[0][0], height)
        for x, y in points:
            context.line_to(x, y)
        context.line_to(points[-1][0], height)
        context.close_path()
        context.fill()

        context.set_source_rgba(*colour, 0.95)
        context.set_line_width(1.0)
        context.set_line_cap(1)   # round
        context.set_line_join(1)
        if dash:
            context.set_dash(dash)
        context.move_to(*points[0])
        for point in points[1:]:
            context.line_to(*point)
        context.stroke()
        context.set_dash([])
