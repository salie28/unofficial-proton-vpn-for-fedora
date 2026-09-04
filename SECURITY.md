# Security

## Report a vulnerability here, or to Proton?

This matters, because most of the security surface is not ours.

**Report to Proton** if it concerns the VPN itself: the tunnel, encryption,
DNS or IP leaks, the kill switch, credentials, or their API. This project does
not implement any of that. It calls into Proton's own controller and their
installed backend does the work. Their process is at
<https://proton.me/security/bug-bounty>.

**Report here** if it concerns this app specifically:

- the interface claiming you are protected when you are not
- our installer or uninstaller touching something it should not
- our own files (`~/.config/unofficial-protonvpn/`) being written unsafely
- anything that makes Proton's app behave differently after installing this

## How to report

Open a [security advisory](https://github.com/salie28/unofficial-proton-vpn-for-fedora/security/advisories/new)
rather than a public issue, and give it a few days.

This is one person's side project, not a funded team. There is no bounty and
no guaranteed response time.

## What this app can and cannot do

Worth knowing when judging severity:

- **It cannot drop your tunnel or disable your kill switch.** Both are held by
  NetworkManager and the root daemon `me.proton.vpn.split_tunneling.service`.
  No GUI holds them up, so no GUI can take them down.
- **It runs entirely as your user.** No root, no systemd units, no system DBus
  services. The installer writes two things under `~/.local`.
- **It never modifies Proton's files.** You can check with
  `rpm -V proton-vpn-gtk-app`, which should print nothing.
- **It handles no credentials.** Login is Proton's own widget, talking to their
  session code. This project never sees a password or a token.

The realistic worst case is a misleading interface: showing "Protected" when
the tunnel is down. That is treated as the most serious class of bug here, and
is why the connection state is cleared the moment it stops being connected
rather than being allowed to go stale.
