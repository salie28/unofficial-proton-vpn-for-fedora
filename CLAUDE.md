# Unofficial Proton VPN - working notes

A separate GTK4 app that imports the officially installed, unmodified
`proton.vpn.app.gtk` at runtime and presents Proton's **Windows** layout on
Linux. Not a fork, not a patch. Read `PLAN.md` first - it is the spec.

## The one rule

**Installing this must never break anyone's VPN.** It is satisfied structurally:
the tunnel is a NetworkManager connection and the kill switch is a separate NM
device, both held by NM and the root daemon `me.proton.vpn.split_tunneling.service`.
No GUI holds the tunnel up.

Rules that follow: read-only on everything Proton owns (never write
`site-packages`, never write `~/.config/Proton/VPN/settings.json`), no root,
never reimplement connection logic (always call their `Controller`), fail with
a clear message rather than a half-built window, never vendor their code.

Check after changes: `rpm -V proton-vpn-gtk-app` must print nothing.

## Commands

```bash
python3 -m unittest discover -s tests          # 214 tests, all must pass
tools/dev-restart.sh                           # restart safely (see below)
./install.sh                                   # two files under ~/.local, no root
env PYTHONPATH=$PWD/src python3 -sP -m unofficial_protonvpn   # run it

# Render the layout to PNG headlessly (GNOME Wayland blocks screenshots)
python3 tools/render.py --out x.png --connected --traffic --real-servers
python3 tools/render.py --out x.png --free      # the paid-plan gate
python3 tools/render.py --out x.png --page recents

python3 tools/make-icons.py                    # regenerate icons from logo.png
python3 tools/make-map.py <ne_110m…geojson>    # regenerate map_data.py
```

## How it hooks into their code

Three substitutions, all rebinding names **in our own process only** - nothing
of Proton's is edited:

1. **Identity** - `identity.claim_application_id()` sets
   `proton.vpn.app.gtk.util.APPLICATION_ID` to ours. Must run **before**
   `proton.vpn.app.gtk.app` is imported, because `app.py` does
   `from ...util import APPLICATION_ID` at module level. `__main__.py` enforces
   the order and `verify_identity_took_effect()` checks it took.
2. **Layout** - `widgets/main_widget.install()` rebinds
   `…widgets.main.main_window.MainWidget` to our subclass, whose
   `_create_vpn_widget()` returns `WindowsStyleVPNWidget`. Called from
   `App.do_activate` before the window is built. Login/2FA/logout stay theirs.
3. **Styling** - `overlay.css` loads at `PRIORITY_USER` (800); theirs loads at
   `PRIORITY_APPLICATION` (600), so ours wins.

`WindowsStyleVPNWidget` subclasses their `VPNWidget` and only **re-parents** its
children into three columns, so `load()`, `display()`, `status_update()` and
`unload()` keep working.

## Gotchas that already cost time - do not rediscover these

- **`status_update()` runs on the executor thread, not the GTK main thread.**
  `Controller.get_settings()` (and `get_setting_attr`) do
  `executor.submit(...).result()` - calling them from `status_update` deadlocks
  the app (it waits on the executor from inside the executor). Their own
  `VPNWidget.status_update` only does `GLib.idle_add`. Anything touching widgets
  or settings must hop to the main thread. There is a regression test.
- **`do_measure` is never called on a `Gtk.Box` subclass.** GTK4 measures
  through the layout manager. To pin the sidebar width: turn off
  `propagate-natural-width` on the scrolling children *and* let row labels
  ellipsize (a label that cannot ellipsize reports a large minimum, and
  minimums win). Both halves are needed.
- **`Gtk.Widget.do_snapshot(w, snapshot)` skips `w`'s own CSS background.** It
  is the vfunc: children render fully, the root's background does not. In
  `tools/render.py` we snapshot a *holder* so the widget is a child. Symptom
  was bare transparent edges that never appear in the running app.
- **`TierEnum` is an `IntFlag` with `FREE = 0`**, so `FREE` is invisible when
  you iterate it. Compare against `0`.
- **Proton emits `Connected` more than once per connection** (feature flags
  arrive after the tunnel is up). Recents dedupe on it.
- **Their `MainWindow` is fixed at 450×700 and `set_resizable(False)`.** We
  override to 1180×780, resizable, min 900×600 - three columns do not fit
  otherwise, and that was the cause of the overlapping panels.
- **Never SIGKILL the app, and give SIGTERM time to land.** Proton writes
  `~/.cache/Proton/VPN/serverlist.json` (24 MB) in one go; killing mid-write
  truncates it. Their code recovers by refetching, but it is avoidable: use
  `tools/dev-restart.sh`, which waits for a clean exit and then checks the
  cache still parses.
- **`RecentsStore` caches `_servers` for the life of the instance.** The window
  and the tray hold separate stores over one file; the tray writes, so the
  window served a stale list and Recents looked broken in the app while working
  in the tray. `reload()` drops the cache - `RecentsView.refresh()` calls it.
- **`GLib.idle_add(future.result)` repeats forever.** Idle sources repeat while
  the callback returns something truthy, and `Future.result()` returns the
  connection result - so the source never removes itself, and a failed call
  re-raises on every pass. Symptom: Proton's error dialog opening and closing
  about twenty times a second. Always go through `futures.report_failure`,
  which returns `GLib.SOURCE_REMOVE`.
- **Multi-step `str.replace` edits can silently corrupt code** when a later
  pattern matches text an earlier one just inserted. That deleted the line
  computing `y` in the chart's `_plot`, leaving every point reusing a stale
  value - a chart that twitched rather than crashed. Read the function back
  after a batch of replacements.
- **Tests must never depend on a live tunnel.** `TrafficMeter` re-discovers
  its interface whenever the counters vanish, so tests that only patch
  `read_counters` pass while a VPN happens to be connected and fail when it is
  not. Patch `find_tunnel_interface` as well.
- **Geometry tests do not prove anything renders.** A missing `_draw_marker`
  shipped because every backdrop test checked coordinates and nothing drew;
  in the app it was an `AttributeError` every frame behind Proton's "unexpected
  error" dialog. `tests/test_backdrop.py` now draws to a real Cairo surface,
  including every country Proton offers.
- **Proton's country codes are not always ISO.** Their `UK` is ISO `GB`;
  `backdrop.COUNTRY_ALIASES` maps them. About ten places they offer have no
  1:110m outline at all (Hong Kong and Macao are not sovereign states, the rest
  are too small) and are marked with a dot at the server's own coordinates.
- **Frame a country on its largest landmass.** France owns French Guiana, so
  framing all of a country's territory put the camera in the Atlantic.
- **`Gtk.Popover.popup()` on a widget with no toplevel segfaults** (not an
  exception - the process dies). `_show_menu` checks `button.get_root()` first.
- Screenshots are **not** available (GNOME Wayland returns AccessDenied). Use
  `tools/render.py`. Ask the user for a screenshot when the real window matters.
  Faint horizontal banding in rendered PNGs is a Cairo tiling artifact of the
  harness, not something the running app shows.
- **The harness cannot show CSS-class changes made just before the snapshot.**
  GTK revalidates styles on the frame clock, which does not tick in the
  renderer, so a widget whose classes changed keeps its previous colours in the
  PNG. Symptom: a button correctly labelled "Disconnect" rendered in the
  Connect colour. Verify state-dependent *colour* in the running app, not in a
  render - check the classes instead, which are accurate.

## Layout

Matches the Windows client's structure: the sidebar and rail run the **full
window height**, and the status line + stats are overlaid on the map behind a
gradient fade - not a bar across the bottom. Getting this wrong is what made
the panes look cut off.

```
tier notice (banner)                     ← free accounts only
┌──────────────┬────────────────────┬──────┐
│ sidebar 280  │  flag + country    │ rail │
│ search       │  server id         │  84  │
│ Recents /    │  Connect button    │      │
│ Countries    │                    │      │
│ filter tabs  │  map (highlights   │      │
│ Fastest ctry │   connected country)  │      │
│ server list  │                    │      │
│              │ 🔒 Protected • …   │      │
│              │ stats + graph      │      │
└──────────────┴────────────────────┴──────┘
+ full-window free-account gate, over everything, until acknowledged
```

## Decisions made (do not silently revisit)

- **Profiles are cut** - impossible on Linux, see below. **Port forwarding is
  supported on Linux** (`settings.features.port_forwarding`, and they ship a
  `port_forward_widget.py`); PLAN.md cut it as scope, not capability.
- **The map is worldwide and pans to the connected country**, animated. The
  span floor is deliberately wide (58°): the outlines are 1:110m, so zooming
  close turns Belgium into a pentagon. Rings that cross the antimeridian are
  skipped or they draw a line across the world.
- **The tray icon follows the connection** - gold connected, grey not. Done by
  overriding their `TrayIndicator` icon constants; their own code switches them.
- **Paid plans only**, warned softly: a full-window gate for free accounts with
  a "Yes, I understand" button, plus a slim banner behind it. It warns, it never
  blocks or disables anything.
- **The centre block is ours** (`connection_panel.py`), not Proton's
  `VPNConnectionStatusWidget`. Theirs is built for a 450px column: it lays its
  children out left-and-right across whatever width it gets, strands the country
  name on the left, and draws outside its own allocation when constrained. Five
  different alignment fixes failed before replacing it. Theirs stays alive as a
  connection-state subscriber, just not shown.
- **Auto connect sits at the top of the rail**, above NetShield. It writes
  `app_configuration.connect_at_app_startup`: unset = off, `"FASTEST"`, or a
  country code / server name (their `_connect_to` splits on `"#"`). Rather than
  build a server picker, it offers whatever you are connected to right now -
  the user's own idea, and it avoids the whole selection UI. Labels show
  **country names**; the stored value stays the code.
- **Port forwarding is deliberately not in the rail.** It is supported on Linux
  and was briefly added, then removed: rarely changed, and it already lives in
  their settings panel.
- **The rail** has a **Protocol** button between Split tunnelling and Settings -
  not in the Windows app, added because switching protocol is otherwise buried.
  It writes `settings.protocol` through their own accessor.
- **The rail**: NetShield and Kill switch are real toggles via their
  `get_setting_attr` / `save_setting_attr`. A *permanent* kill switch is never
  switched off by one click - it opens their settings instead. Split tunnelling
  and Settings open their settings window (those panels are wired to a conflict
  resolver and notification bar; lifting them out is the coupling PLAN.md §7 #3
  warns about).
- **The rail floats over the map** as a translucent rounded card, not a solid
  column - the Windows app floats both panes on a full-width map. The sidebar
  is still a column; floating it means the map must span the whole window.
  GTK4 has no acrylic blur; a translucent panel is the closest equivalent and
  Proton's own fallback is a flat colour.
- **Map land stays understated** (white at 4% fill, 8.5% stroke). Brighter,
  Proton-tinted land was tried and rejected: the backdrop should not compete
  with the panel in front of it. The connected country is gold.
- **The country chooser is a lighter panel** (`background_weak`, 1px lighter
  border, radius 10) so it separates from the window behind it - that, not the
  map, was what needed contrast.
- **The map** is stylised, not realistic, in our black/violet palette - the user
  explicitly does not want Proton's teal. Outlines are public-domain Natural
  Earth, clipped and simplified into `widgets/map_data.py`. The connected
  country is highlighted by ISO alpha-2 code.
- **The graph** was cut in PLAN.md and later asked for; it is in the stats bar.
- **Animations are done and deliberate.** CSS transitions on every interactive
  state; keyframes for the connecting pulse and for entrances (GTK4 CSS has no
  transforms, so slides come from `Gtk.Stack`, not CSS). Frame-clock animations
  where a value has to be interpolated: the map pan, the highlight fade, the
  chart sliding a new sample in over its 1s interval, and the server-load bar
  easing. `add_tick_callback` is the tool; it stops itself when it reaches 1.0.
- The logo is the user's own `logo.png`. It reads as Proton's mark recoloured,
  which PLAN.md §2 rules out on trademark grounds - flagged, user accepted for
  now, private repo, easy to swap (`tools/make-icons.py`).

## Reference material

`reference/win-app` is a shallow clone of Proton's **Windows** client
(github.com/ProtonVPN/win-app, GPL-3.0, C#/WPF). It is the design reference for
placement, spacing and structure - the agreed approach is to take the Windows
layout and adapt where Linux lacks the feature. Gitignored, never vendored.

`reference/proton-vpn-gtk-app` is the matching upstream Linux source (v4.18.1),
kept for reading widget internals and CSS selectors.

**Their Windows palette *is* black/violet**, which is what the user wanted - so
`overlay.css` now uses their real tokens rather than invented ones:

| token | value |
|---|---|
| background (window, sidebar, rail) | `#16141C` |
| panel / card | `#292733` |
| text norm / weak / hint | `#FFF` / 70% / 50% |
| accent, Connect button | `#6D4AFF` (hover `#7C5CFF`, active `#8A6EFF`) |
| Disconnect button | `#4A4658`, red only on hover (`#995B70`) |
| protected | `#2CFFCC` · unprotected `#F7607B` |
| graph download / upload | `#4BB99D` solid / `#F7607B` dashed 3,3 |

Type scale: country name 28/36 SemiBold, server line 16/20 SemiBold weak,
button 16 SemiBold with padding 24,8,24,10 and radius 4, stat label 12/16
normal, stat value 14/20 SemiBold. Chart: 60 points at 1/s, 3 dashed axis
lines, scale = peak x 1.1 rounded up. Their sidebar is 280 wide (ours 340);
their filter tabs use a 16x3 pill indicator, not a full underline.

## The repository

Public at <https://github.com/salie28/unofficial-proton-vpn-for-fedora>,
GPL-3.0. `PLAN.md` and `docs/TESTING.md` are gitignored on purpose: useful
locally, noise for anyone cloning. This file is tracked, and is the one piece
of working notes a contributor would want.

Nothing is pinned to a Proton version. `_note_upstream_version` records the
installed version in the log and warns only on a different major series, so
routine Proton releases do not nag.

## Open / next

- **Login, 2FA and logout have never been exercised.** The user stayed logged
  in throughout the build. It is the first thing a stranger hits.
- **The free-account gate** has never been seen; it needs a free account.
- The logo reads as Proton's mark recoloured. The README says so and calls it
  a placeholder; it is the likeliest thing to draw a complaint.
- Dropped by the user: pan/zoom the map, click a country to connect, NetShield
  blocked counters (not exposed on Linux), a settings rework (their window is
  wired to a conflict resolver; low value, high coupling).
- Profiles: **not possible** - the Linux stack has no profile modules and
  `ProtonVPNAPI` has no profile API. It would mean building the feature, which
  is backend work we do not do. Settled, do not revisit.
- Remaining polish: the sidebar/rail could use their acrylic look (GTK has no
  direct equivalent; flat `#16141C` is the documented fallback), and their
  country rows use padding 12,10 / radius 8.
