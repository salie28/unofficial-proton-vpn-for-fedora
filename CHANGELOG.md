# Changelog

## v1.0.1

Checked against Proton VPN 4.18.8 (Fedora 44, November 2026). No changes to
the app were needed; v1.0.0 runs on it as is.

### Fixed

- A layout test asserted on a private list inside Proton's `VPNWidget` that
  4.18.8 removed. The behaviour it stood for, Proton's status widgets still
  receiving every connection state, is unchanged; the test now checks that
  through the widget's signal instead, so it holds on both versions.

## v1.0.0

First release.

A separate application that imports the officially installed, unmodified
`proton.vpn.app.gtk` at runtime and presents Proton's Windows layout on Linux.
Proton's files are never modified and none of their code is vendored.

### Added

- **Three-column window** modelled on Proton's Windows client: country panel,
  connection block over a map, and a quick-access rail, with the status line
  and statistics read through onto the map.
- **World map** that highlights the country you are connected to and animates
  to centre it. Countries with no outline in the data, or that are not
  separate countries, are marked at the server's own coordinates.
- **Traffic chart** with live download and upload, drawn from the tunnel
  interface, plus VPN IP, server load, protocol and session total.
- **Recents.** The official Linux client has no recents list; this keeps its
  own, shared between the window and the tray.
- **Quick-access rail** for auto connect, NetShield, kill switch, split
  tunnelling and protocol. Every entry explains itself on hover, in Proton's
  own wording.
- **Auto connect** that can pin the country or server you are already on,
  rather than asking you to pick from a list or type a country code.
- **Tray menu** with live throughput, quick connect and recent servers.
- **Paid-plan notice** for free accounts: a full-window explanation that warns
  and is dismissed, never one that blocks.

### Notes

- Requires the official Proton VPN Linux app and a paid plan.
- English only.
- Nothing is pinned to a Proton version. A release this has not been tested
  against is recorded in the log; only a different major series is warned
  about. If Proton renames something this depends on, the app says so plainly
  instead of showing a broken window.
