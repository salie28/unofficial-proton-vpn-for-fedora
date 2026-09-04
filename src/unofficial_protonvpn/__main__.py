"""
Entry point.

Order matters and is the whole trick (PLAN.md §3):

    1. patch APPLICATION_ID
    2. only then import anything that reads it

so step 1 happens before this module imports `.app`.
"""

import sys


def main() -> int:
    """Run the app. Returns a process exit code; never raises past this point."""
    from .errors import report_fatal
    from .identity import (
        UpstreamLayoutChanged,
        claim_application_id,
        upstream_version,
        verify_identity_took_effect,
    )

    try:
        # 1. Claim the identity BEFORE proton.vpn.app.gtk.app is imported.
        claim_application_id()

        # 2. Now it is safe to import their code.
        from proton.vpn.app.gtk.controller import Controller
        from proton.vpn.app.gtk.utils.exception_handler import ExceptionHandler
        from proton.vpn.app.gtk.utils.executor import AsyncExecutor

        from .app import UnofficialProtonVPNApp

        verify_identity_took_effect()
    except UpstreamLayoutChanged as error:
        report_fatal(str(error))
        return 1
    except ImportError as error:
        report_fatal(
            "Could not load the official Proton VPN app, which this app builds on.",
            f"Install the proton-vpn-gnome-desktop package first.\n({error})",
        )
        return 1

    _note_upstream_version()

    # Mirrors proton.vpn.app.gtk.__main__.main() - same executor, same
    # controller, same exception handler. PLAN.md §2: never reimplement
    # connection logic, always call their Controller.
    with AsyncExecutor() as executor, ExceptionHandler() as exception_handler:
        controller = Controller.get(executor, exception_handler)
        return UnofficialProtonVPNApp(controller).run(sys.argv)


def _note_upstream_version() -> None:
    """Record which Proton version we are running against.

    Nothing is pinned. This app composes Proton's widget classes, so a version
    it has not seen may work perfectly or may not; either way the right place
    to say so is the log, which is what anyone debugging will read. Writing
    only to stderr was useless: launched from the applications menu, nobody
    ever sees stderr.
    """
    from proton.vpn import logging

    from .branding import SUPPORTED_UPSTREAM_MAJOR, TESTED_UPSTREAM_VERSIONS
    from .identity import upstream_version

    logger = logging.getLogger(__name__)
    version = upstream_version()

    if version.startswith(TESTED_UPSTREAM_VERSIONS):
        logger.info(f"proton-vpn-gtk-app {version} (tested).")
        return

    major = version.split(".", 1)[0]
    message = (
        f"Running against proton-vpn-gtk-app {version}; this app was built "
        f"against {', '.join(TESTED_UPSTREAM_VERSIONS)}.x."
    )

    if major != SUPPORTED_UPSTREAM_MAJOR:
        message += (
            f" That is a different major series to {SUPPORTED_UPSTREAM_MAJOR}.x, "
            "so the layout may not apply. The app will say so plainly rather "
            "than showing a broken window, and the official app is unaffected."
        )
        logger.warning(message)
        sys.stderr.write(message + "\n")
        return

    logger.info(message)


if __name__ == "__main__":
    sys.exit(main())
