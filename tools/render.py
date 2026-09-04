#!/usr/bin/env python3
"""
Render our layout to a PNG, with no VPN connection and nobody watching.

PLAN.md §8's feedback loop, pointed at our own widgets: "Add demo screens for
anything new so it can be iterated visually without launching." Screenshots are
not available on GNOME Wayland from a shell, so this is how the layout gets
checked at a real window size.

    python3 tools/render.py --out shot.png --width 1100 --height 760
    python3 tools/render.py --out shot.png --connected --real-servers

Uses the same GTK machinery Proton's own demo harness does: snapshot the widget
tree into a render node, then rasterise it with the Cairo (software) renderer,
which is consistent across GPUs.
"""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Graphene, Gsk, Gtk, GLib  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

SERVER_CACHE = Path.home() / ".cache" / "Proton" / "VPN" / "serverlist.json"


def build_controller(connected: bool, real_servers: bool):
    """A Controller stand-in good enough to render against."""
    controller = MagicMock(name="Controller")
    controller.user_tier = 2
    controller.user_logged_in = True
    controller.connection_disconnected = not connected
    controller.get_settings.return_value.protocol = "wireguard"
    settings = {"settings.features.netshield": 2, "settings.killswitch": 1,
                "settings.protocol": "wireguard"}
    controller.get_setting_attr.side_effect = lambda name: settings.get(name)
    controller.get_available_protocols.return_value = []
    controller.server_list.get_by_name.return_value = SimpleNamespace(
        load=36, location="Vienna", exit_country="AT", features=[])

    # Make the mock's *current* status match what we are about to render. Their
    # VPNWidget broadcasts this onto the idle loop, and if it disagrees it flips
    # the CSS classes back - after which GTK would need a frame clock to
    # restyle, which the renderer does not have. The picture then shows the
    # previous colours (a violet "Disconnect" button).
    if connected:
        controller.current_connection_status = connected_state()

    if real_servers and SERVER_CACHE.exists():
        from proton.vpn.session.servers import ServerList
        server_list = ServerList.from_dict(json.loads(SERVER_CACHE.read_text()))
        controller.server_list = server_list
        # Point the mock at a server that actually exists, so widgets looking
        # up the current connection do not raise into the render.
        real = next((s for s in server_list.logicals
                     if s.name.startswith("AT")), server_list.logicals[0])
        controller.current_connection_status.context.connection.server_name = real.name
    return controller


def connected_state(server_name="AT#215"):
    state = MagicMock()
    type(state).__name__ = "Connected"
    state.context.connection.server_name = server_name
    state.context.connection.protocol = "wireguard"
    state.context.event.context.connection_details = SimpleNamespace(
        device_ip="203.0.113.42", device_country="AT",
        server_ipv4="203.0.113.7", server_ipv6=None)
    return state


def seed_traffic(stats_bar):
    """Feed the chart a minute of plausible traffic, so it can be looked at."""
    import math
    import random

    from unofficial_protonvpn.traffic import format_rate

    random.seed(7)  # same picture every run, so renders are comparable
    down = up = 0.0
    for tick in range(60):
        burst = 90_000 * max(0.0, math.sin(tick / 5.0)) ** 3
        down = 12_000 + burst + random.uniform(0, 9_000)
        up = 6_000 + burst * 0.35 + random.uniform(0, 5_000)
        stats_bar.graph.push(down, up)

    stats_bar._cells["down"].set_text(f"\u2193 {format_rate(down)}")
    stats_bar._cells["up"].set_text(f"\u2191 {format_rate(up)}")

    # A plausible session total, so screenshots do not show a placeholder in
    # the middle of otherwise populated figures.
    from unofficial_protonvpn.traffic import format_bytes
    stats_bar._cells["total"].set_text(format_bytes(3_400_000_000))
    stats_bar.load_bar.set_load(0.36)


def render(widget: Gtk.Widget, window: Gtk.Window, path: Path,
           width: int, height: int, before_snapshot=None) -> None:
    """Lay the widget out at exactly (width, height) and write a PNG."""
    # Snapshot the widget's *holder*, not the widget itself.
    #
    # Gtk.Widget.do_snapshot is the vfunc: it draws children through the full
    # pipeline (so their CSS backgrounds appear) but skips the CSS box of the
    # widget it is called on. Snapshotting the widget directly therefore loses
    # its own background and leaves bare, transparent edges that the running
    # app never shows. As a child of the holder, it is drawn normally.
    holder = widget.get_parent()
    if holder is None:
        raise SystemExit("the widget must be inside a holder to render correctly")
    holder.allocate(width, height, -1, None)

    # Let the layout settle before snapshotting. Without this the snapshot can
    # use transforms from the previous allocation, and the picture disagrees
    # with where the widgets actually are - which sends you chasing layout bugs
    # that do not exist.
    context = GLib.MainContext.default()
    for _ in range(200):
        if not context.pending():
            break
        context.iteration(False)
    holder.allocate(width, height, -1, None)

    # Apply the demo state *after* the queue has drained. Their VPNWidget keeps
    # broadcasting the mock controller's (disconnected) status onto the idle
    # loop, and anything applied before that lands gets silently undone - which
    # showed up as a Connect-coloured button labelled "Disconnect".
    if before_snapshot is not None:
        before_snapshot()
        # Changing CSS classes does not restyle immediately: GTK revalidates
        # styles on the frame clock. Snapshotting straight after the change
        # captures the *previous* colours - which is why a button correctly
        # labelled "Disconnect" still rendered in the Connect colour.
        context = GLib.MainContext.default()
        for _ in range(500):
            if not context.pending():
                break
            context.iteration(False)
        holder.allocate(width, height, -1, None)

    widget = holder

    snapshot = Gtk.Snapshot.new()
    Gtk.Widget.do_snapshot(widget, snapshot)
    node = snapshot.to_node()
    if node is None:
        raise SystemExit("nothing was drawn - the widget tree produced no render node")

    renderer = Gsk.CairoRenderer.new()
    renderer.realize(window.get_surface())
    try:
        texture = renderer.render_texture(
            node, Graphene.Rect().init(0, 0, width, height))
    finally:
        renderer.unrealize()

    path.parent.mkdir(parents=True, exist_ok=True)
    texture.save_to_png(str(path))
    print(f"wrote {path} ({width}x{height})")
    return width, height


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="layout.png", type=Path)
    parser.add_argument("--width", type=int, default=1100)
    parser.add_argument("--height", type=int, default=760)
    parser.add_argument("--connected", action="store_true",
                        help="render as if a VPN connection is up")
    parser.add_argument("--real-servers", action="store_true",
                        help="populate from the real cached server list")
    parser.add_argument("--page", choices=("countries", "recents"),
                        default="countries")
    parser.add_argument("--free", action="store_true",
                        help="render as a free account (shows the paid-plan notice)")
    parser.add_argument("--traffic", action="store_true",
                        help="seed the chart with a minute of plausible traffic")
    parser.add_argument("--country", default="AT",
                        help="ISO alpha-2 country to highlight on the map")
    args = parser.parse_args()

    from unofficial_protonvpn.style import load_overlay_css
    from unofficial_protonvpn.widgets.main_layout import WindowsStyleVPNWidget

    app = Gtk.Application(application_id="io.github.yourhandle.UnofficialProtonVPN.render")
    result = {"code": 1}

    def on_activate(application):
        from gi.repository import Gdk
        # MainWindow forces the dark theme, so the harness must too or the
        # render shows colours no user ever sees.
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.props.gtk_application_prefer_dark_theme = True

        from proton.vpn.app.gtk.assets.style import load_app_css
        load_app_css(Gdk.Display.get_default())   # Proton's, at priority 600
        load_overlay_css(Gdk.Display.get_default())  # ours, at 800

        controller = build_controller(args.connected, args.real_servers)
        widget = WindowsStyleVPNWidget(controller, MagicMock(), notifications=MagicMock())

        tier = 0 if args.free else 2
        if args.real_servers and SERVER_CACHE.exists():
            widget.display(tier, controller.server_list)
        else:
            widget.tier_notice.update_for_tier(tier)
        widget.sidebar.show_page(args.page)

        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        holder.append(widget)

        window = Gtk.Window(application=application)
        window.set_default_size(args.width, args.height)
        window.set_child(holder)
        window.present()

        def capture():
            # Drain the idle queue first. display() queues a *disconnected*
            # state broadcast (the mock controller has no real status), and if
            # it runs after we set the connected state it silently undoes it -
            # which shows up as a Connect-coloured button labelled Disconnect.
            context = GLib.MainContext.default()
            for _ in range(500):
                if not context.pending():
                    break
                context.iteration(False)

            def apply_demo_state():
                if args.connected:
                    state = connected_state()
                    widget.stats_bar._apply_state(state)
                    widget.connection_panel._apply_state(state)
                    widget.connection_panel._end_flash()
                    widget.backdrop.set_highlight(args.country, animate=False)
                if args.traffic:
                    seed_traffic(widget.stats_bar)

            try:
                render(widget, window, args.out, args.width, args.height,
                       before_snapshot=apply_demo_state)
                result["code"] = 0
            finally:
                window.destroy()
                application.quit()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(700, capture)

    app.connect("activate", on_activate)
    app.run([])
    return result["code"]


if __name__ == "__main__":
    sys.exit(main())
