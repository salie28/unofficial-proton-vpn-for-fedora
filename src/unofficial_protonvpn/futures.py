"""
Reporting failures from Proton's futures, on the main thread, exactly once.

Every connect/disconnect call returns a `Future`. If it failed we want the
error raised on the GTK main thread so their exception handler can show it -
but the obvious spelling is a trap:

    future.add_done_callback(lambda f: GLib.idle_add(f.result))

`GLib.idle_add` repeats the callback for as long as it returns something
truthy, and `Future.result()` returns the connection result. So that source
never removes itself: it re-fires continuously, and if the call failed it
raises on every pass. Symptom seen in the wild - Proton's error dialog opening
and closing about twenty times a second.

`report_failure` runs once and always returns `GLib.SOURCE_REMOVE`.
"""

from concurrent.futures import Future

from gi.repository import GLib

from proton.vpn import logging

logger = logging.getLogger(__name__)


def report_failure(future: Future, what: str) -> None:
    """Re-raise a failed future on the main thread, once.

    A successful future is ignored. A failed one is re-raised where Proton's
    exception handler can present it, which is what their own code does.
    """
    def on_main_thread() -> bool:
        try:
            future.result()
        except Exception:  # pylint: disable=broad-except
            logger.exception(f"{what} failed.")
            raise
        finally:
            pass
        return GLib.SOURCE_REMOVE

    def when_done(_future: Future) -> None:
        GLib.idle_add(on_main_thread)

    future.add_done_callback(when_done)
