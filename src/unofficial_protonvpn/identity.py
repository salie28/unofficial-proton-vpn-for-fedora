"""
Takes over Proton's application identity before their code observes it.

PLAN.md §3: `APPLICATION_ID` lives in `proton/vpn/app/gtk/util.py` and `app.py`
does `from ...util import APPLICATION_ID` at module level, binding the value at
*import* time. So the patch has to land before `app.py` is first imported.
Get the order wrong and both apps register the same GApplication ID, at which
point launching ours just raises the official window instead.

Importing `proton.vpn.app.gtk.util` is safe to do early: their package
`__init__` only sets up gi/Gtk and logging, it does not pull in `app`.

Nothing here writes to Proton's files - this rebinds a module attribute in our
own process only (PLAN.md §2: read-only on everything Proton owns).
"""

import sys

from .branding import APP_ID

#: The module that must NOT be imported before :func:`claim_application_id` runs.
_LATE_MODULE = "proton.vpn.app.gtk.app"


class UpstreamLayoutChanged(RuntimeError):
    """Proton moved something we depend on. Raised with a human-readable cause."""


def claim_application_id(app_id: str = APP_ID) -> str:
    """Point Proton's APPLICATION_ID at us. Must run before importing their app.

    Returns the id that was set, so callers can log it.
    """
    if _LATE_MODULE in sys.modules:
        # Not recoverable by patching now: app.py already copied the old value
        # into its own namespace.
        raise UpstreamLayoutChanged(
            f"{_LATE_MODULE} was imported before the application ID was patched. "
            "The identity patch must run first, otherwise this app collides with "
            "the official Proton VPN app."
        )

    try:
        from proton.vpn.app.gtk import util
    except ImportError as error:
        raise UpstreamLayoutChanged(
            "The official Proton VPN app does not appear to be installed "
            "(could not import proton.vpn.app.gtk). Install the "
            "proton-vpn-gnome-desktop package first."
        ) from error

    if not hasattr(util, "APPLICATION_ID"):
        raise UpstreamLayoutChanged(
            "proton.vpn.app.gtk.util no longer defines APPLICATION_ID. "
            "This version of Proton VPN is not supported yet."
        )

    util.APPLICATION_ID = app_id
    return app_id


def verify_identity_took_effect() -> None:
    """Confirm `app.py` really picked up our id, once it has been imported.

    Cheap insurance against a silent upstream refactor (e.g. them switching to
    reading the constant lazily), which would otherwise show up as the
    confusing "our launcher opens Proton's window" bug.
    """
    app_module = sys.modules.get(_LATE_MODULE)
    if app_module is None:
        return

    observed = getattr(app_module, "APPLICATION_ID", None)
    if observed != APP_ID:
        raise UpstreamLayoutChanged(
            f"Expected {_LATE_MODULE} to use application ID {APP_ID!r}, "
            f"but it is using {observed!r}. Proton changed how the application "
            "ID is resolved; this app would collide with the official one."
        )


def upstream_version() -> str:
    """Installed version of proton-vpn-gtk-app, or 'unknown'."""
    from importlib.metadata import version, PackageNotFoundError
    try:
        return version("proton-vpn-gtk-app")
    except PackageNotFoundError:
        return "unknown"
