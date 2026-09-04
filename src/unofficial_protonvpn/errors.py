"""
Fail-safe error reporting.

PLAN.md §2: "If something Proton renamed breaks us, show a clear message; never
a half-built window or a traceback."
"""

import sys

from .branding import APP_NAME


def report_fatal(message: str, detail: str = "") -> None:
    """Tell the user what broke, in words, on stderr and on screen if possible.

    Always writes to stderr first: the GUI path is exactly the thing that may be
    broken, so it must never be the only channel.
    """
    sys.stderr.write(f"\n{APP_NAME}: {message}\n")
    if detail:
        sys.stderr.write(f"{detail}\n")
    sys.stderr.write(
        "\nThe official Proton VPN app is unaffected and can still be used.\n"
        "Your VPN connection is held by NetworkManager, not by this app, so\n"
        "nothing about your tunnel or kill switch has changed.\n\n"
    )
    sys.stderr.flush()

    _try_show_dialog(message, detail)


def _try_show_dialog(message: str, detail: str) -> None:
    """Best-effort GTK alert. Silently gives up - stderr already has the message."""
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk, Gio, GLib
    except Exception:  # pylint: disable=broad-except
        return

    try:
        app = Gtk.Application(
            application_id=None,
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )

        def on_activate(application):
            dialog = Gtk.AlertDialog()
            dialog.set_modal(True)
            dialog.set_message(f"{APP_NAME} could not start")
            body = message + (f"\n\n{detail}" if detail else "")
            body += (
                "\n\nYour VPN connection is unaffected - it is held by "
                "NetworkManager, not by this app."
            )
            dialog.set_detail(body)
            dialog.set_buttons(["Close"])

            def done(*_args):
                application.quit()

            dialog.choose(None, None, done)
            # Keep the application alive until the dialog is answered.
            application.hold()
            GLib.timeout_add_seconds(60, application.quit)

        app.connect("activate", on_activate)
        app.run([])
    except Exception:  # pylint: disable=broad-except
        return
