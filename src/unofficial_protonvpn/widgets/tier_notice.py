"""
The paid-plan notice.

PLAN.md §1: "Paid accounts only. Documented in the README, and enforced softly
at login via `ProtonVPNAPI.user_tier` - show 'this app requires a paid plan'
rather than letting free users hit broken states."

Softly is the operative word. This explains the situation and stays out of the
way; it does not block the window, disable the server list, or prevent anyone
from connecting. A free user's session, settings and tunnel are all Proton's,
and nothing here interferes with them.
"""

from gi.repository import Gtk

from proton.vpn import logging

from ..branding import APP_NAME

logger = logging.getLogger(__name__)

#: TierEnum is an IntFlag whose FREE member is 0, so it does not show up when
#: the enum is iterated. Comparing against the number keeps this working even
#: if the enum moves.
FREE_TIER = 0


def is_free_tier(user_tier) -> bool:
    """Whether this is a free account. Unknown tiers count as paid.

    Erring towards "paid" is deliberate: a wrong guess should never nag a
    paying customer about upgrading.
    """
    try:
        return int(user_tier) == FREE_TIER
    except (TypeError, ValueError):
        return False


class TierNotice(Gtk.Box):
    """A banner explaining that this app expects a paid plan."""

    MESSAGE = (
        f"{APP_NAME} is built for paid Proton VPN plans. "
        "On a free account most servers and features here will not be available."
    )

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.add_css_class("tier-notice")
        self.set_visible(False)

        for setter in (self.set_margin_start, self.set_margin_end):
            setter(16)
        self.set_margin_top(10)
        self.set_margin_bottom(2)

        icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        icon.set_valign(Gtk.Align.START)
        self.append(icon)

        label = Gtk.Label(label=self.MESSAGE)
        label.set_wrap(True)
        label.set_xalign(0)
        label.set_hexpand(True)
        label.add_css_class("tier-notice-label")
        self.append(label)

        dismiss = Gtk.Button(label="Dismiss")
        dismiss.add_css_class("flat")
        dismiss.set_valign(Gtk.Align.CENTER)
        dismiss.connect("clicked", lambda *_: self.set_visible(False))
        self.append(dismiss)

    def update_for_tier(self, user_tier) -> None:
        """Show the notice only for free accounts."""
        free = is_free_tier(user_tier)
        if free:
            logger.info("Free account detected; showing the paid-plan notice.",
                        category="ui.tier", event="free_account")
        self.set_visible(free)


class FreeAccountGate(Gtk.Box):
    """A full-window warning shown to free accounts before anything else.

    Deliberately unmissable: it covers the whole window, so the app cannot be
    used without reading it first. It is a warning, not a lock - the button at
    the bottom dismisses it and everything underneath works exactly as before.
    Nobody is prevented from using their own VPN.
    """

    TITLE = "This app needs a paid Proton VPN plan"

    BODY = (
        f"{APP_NAME} is built for paid Proton VPN plans, and on a free account "
        "it will not work as intended."
    )

    DETAIL = (
        "Most servers are unavailable to free accounts, and Secure Core, P2P "
        "and Tor are paid features. Parts of this app expect them to be there, "
        "so screens can look wrong, appear empty, or stop responding as you "
        "would expect."
    )

    REASSURANCE = (
        "Your VPN itself is not affected. The official Proton VPN app "
        "continues to work normally, and nothing here changes your connection, "
        "your settings or your account."
    )

    ACKNOWLEDGE = "Yes, I understand"

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("free-gate")
        self.set_visible(False)
        # Cover everything underneath, and swallow clicks meant for it.
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_can_target(True)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        body.set_valign(Gtk.Align.CENTER)
        body.set_halign(Gtk.Align.CENTER)
        body.set_vexpand(True)
        body.set_size_request(520, -1)
        for setter in (body.set_margin_start, body.set_margin_end):
            setter(48)

        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.set_pixel_size(56)
        icon.add_css_class("free-gate-icon")
        body.append(icon)

        title = Gtk.Label(label=self.TITLE)
        title.add_css_class("free-gate-title")
        title.set_wrap(True)
        title.set_justify(Gtk.Justification.CENTER)
        body.append(title)

        for text_block, css_class in (
            (self.BODY, "free-gate-body"),
            (self.DETAIL, "free-gate-detail"),
            (self.REASSURANCE, "free-gate-detail"),
        ):
            label = Gtk.Label(label=text_block)
            label.add_css_class(css_class)
            label.set_wrap(True)
            label.set_justify(Gtk.Justification.CENTER)
            label.set_max_width_chars(56)
            body.append(label)

        self.append(body)

        # The acknowledgement sits at the bottom, as asked.
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        footer.set_valign(Gtk.Align.END)
        footer.set_halign(Gtk.Align.CENTER)
        footer.set_margin_bottom(40)

        self.acknowledge_button = Gtk.Button(label=self.ACKNOWLEDGE)
        self.acknowledge_button.add_css_class("free-gate-button")
        self.acknowledge_button.add_css_class("suggested-action")
        self.acknowledge_button.connect("clicked", self._on_acknowledged)
        footer.append(self.acknowledge_button)

        self.append(footer)

    def _on_acknowledged(self, *_args):
        logger.info("Free-account warning acknowledged.",
                    category="ui.tier", event="acknowledged")
        self.set_visible(False)

    def update_for_tier(self, user_tier) -> None:
        """Show the warning only for free accounts, and only until dismissed."""
        self.set_visible(is_free_tier(user_tier))
