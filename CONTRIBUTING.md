# Contributing

Bug reports are the most useful thing you can send. This has been tested by
one person on one distribution, so almost any real-world use finds something.

## Reporting a bug

Include your distribution, your `proton-vpn-gtk-app` version
(`rpm -q proton-vpn-gtk-app` or `pip show proton-vpn-gtk-app`), and what you
expected against what happened. A screenshot settles most layout questions in
one step.

If the app failed to start, the log is at `~/.cache/Proton/VPN/logs/`.

## Before you open a pull request

Run the tests:

```bash
python3 -m unittest discover -s tests
```

Check Proton's install is still untouched:

```bash
rpm -V proton-vpn-gtk-app
```

Empty output. If that prints anything, something has written to files this
project must never write to.

## The rules this project holds to

These are not style preferences. Breaking one is a bug regardless of what it
enables:

1. **Never break someone's VPN.** The tunnel and kill switch belong to
   NetworkManager and Proton's root daemon. Nothing here may hold them up,
   take them down, or claim protection that is not there.
2. **Read-only on everything Proton owns.** Never write to `site-packages` or
   to their `~/.config/Proton/VPN/settings.json`. Our settings live in our own
   directory.
3. **No root.** No systemd units, no NetworkManager configuration, no system
   DBus services. Installing is two files under `~/.local`.
4. **Never reimplement connection logic.** Every connect and disconnect goes
   through Proton's `Controller`.
5. **Never vendor Proton's code.** We import the installed copy.
6. **Fail with a sentence, not a traceback.** If Proton renames something we
   depend on, say so plainly rather than showing half a window.

## Working on the interface

`CLAUDE.md` documents the traps that have already cost time: the threading
rule around `status_update`, why `do_measure` does nothing on a `Gtk.Box`, and
why a render can disagree with the running app. Read it before wondering why
something behaves oddly. It is kept current.

Screenshots come from the renderer, not a screen capture:

```bash
python3 tools/render.py --out shot.png --connected --traffic --real-servers
```

Restart the app with `tools/dev-restart.sh` rather than killing it. Proton
writes a 24 MB server cache in one go, and killing it mid-write truncates the
file.
