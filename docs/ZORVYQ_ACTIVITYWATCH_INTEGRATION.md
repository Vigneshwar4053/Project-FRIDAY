# ActivityWatch integration — Phase 2D-LIVE

Updated 2026-11-10. This document supersedes the earlier download proposal.

## Verified installation and health

The existing official [ActivityWatch v0.14.1 release](https://github.com/ActivityWatch/activitywatch/releases/tag/v0.14.1) was reused; it was not downloaded again during LIVE. Source checkout: `third_party/activitywatch/`, official origin `https://github.com/ActivityWatch/activitywatch.git`, commit `2b995517487ba6e1e572bd4d4e53f9dcc43c90a2`. No upstream source edits or install scripts were used. The reviewed Makefile requires Python components, web UI, and Rust submodule builds; the release ZIP avoids mixing those toolchains into ZORVYQ's environment.

Runtime: `third_party/activitywatch-runtime/v0.14.1/activitywatch/`. Archive size 196,236,767 bytes; SHA-256 `211514a8912c0a399a8c7048101b699e0a2fedb5e81b5ed224304d5c8e091f2a`. Archive paths and symlinks were checked before extraction in the preceding implementation. `third_party/activitywatch-manifest.json` records the upstream identity and individual executable checksums; discovery checks them before launch. This is checksum verification against official HTTPS release metadata, not a signed reproducible-build attestation.

The isolated classic release supplies Python/Rust servers, window/AFK watchers and an input watcher. ZORVYQ launches **only** the Python server and separately reviewed `aw-awatcher`. It never launches `aw-qt`, `aw-sync`, `aw-watcher-input`, the classic window watcher, or the classic input-based AFK watcher. No pip/apt/system-wide dependencies were installed. Both selected binaries pass `--help`; shared-library inspection found no missing libraries on this Ubuntu x86_64 host.

A disposable, empty server was actually launched, returned HTTP 200 from `/api/0/buckets/`, and had exactly a `127.0.0.1:5600` listener. It was then stopped and its temporary directories removed. No watchers were launched, no owner events observed, and no live model inference performed. Installed, running, responsive, watcher connected, and real activity accepted are separate states: **installed and server smoke-tested; watcher activation and owner acceptance pending**.

```bash
.venv/bin/python -B scripts/verify_activitywatch_runtime.py
# Optional disposable server-only check; never starts watchers:
.venv/bin/python -B scripts/verify_activitywatch_runtime.py --server-check
```

## GNOME Wayland

The inherited desktop reports `XDG_SESSION_TYPE=wayland`, `XDG_CURRENT_DESKTOP=ubuntu:GNOME`; `gnome-shell --version` reports 50.1. The existing GUI autostart entry points to this checkout and was not modified. System-bus `loginctl` is unavailable in the execution sandbox, so no additional session-bus inspection of owner activity was attempted.

The standard watcher cannot cover native GNOME Wayland windows ([upstream FAQ](https://docs.activitywatch.net/en/latest/faq.html)). Selected integration: [2e3s/awatcher](https://github.com/2e3s/awatcher), the alternative bundled by upstream's experimental Wayland distribution. Its standalone v0.4.0 watcher is installed at `third_party/awatcher-runtime/v0.4.0/aw-awatcher`, avoiding another server/tray bundle. Official project release ZIP: 4,748,790 bytes; SHA-256 `8cdbb99916800bc509afc28785d85d5a1f74fdcea0d378d8019e2244df507eca`. Reviewed source checkout: `third_party/awatcher/` at `6e3aeee8fe0cfbc870cc41bca0c357339f63e864`. Source review covered GNOME window/idle D-Bus use, filter ordering, heartbeat schemas and retry behavior; release-binary behavior still requires owner acceptance.

It uses the Focused Window D-Bus GNOME extension for application identifiers and Mutter IdleMonitor for elapsed idle time. No keyboard data or password-field access is needed. The following steps require the owner:

1. Review [Focused Window D-Bus](https://extensions.gnome.org/extension/5592/focused-window-d-bus/) and its [source](https://github.com/flexagoon/focused-window-dbus). The extension exposes focused-window class/title and other window metadata to session D-Bus clients. This expands access for local applications; ZORVYQ retains only the approved metadata described below.
2. Install a listed GNOME 50-compatible version through GNOME's ordinary extension installation UI. The listing currently includes versions 11 and 12 for Shell 50. Do not force incompatible versions.
3. Activate it yourself using GNOME Extensions, or after installation:
   `gnome-extensions enable focused-window-dbus@flexagoon.com`
4. Reopen ZORVYQ. In Settings → Activity & Privacy, review the application identifiers, enable **Manage local ActivityWatch server and GNOME watcher**, then enable application monitoring (or Start monitoring now).
5. The controller checks only D-Bus introspection before starting its watcher. It never installs/enables the extension or calls Shell Eval. Missing extension, idle evidence, or fresh foreground events produces **Watcher unavailable**, never a fabricated app.

Managed upstream filtering is generated before watcher launch: sensitive/excluded and unapproved applications become only the neutral `__zorvyq_excluded__` marker with a blank title; approved app IDs are retained with blank titles. This neutral transition closes preceding approved activity when returning to an unapproved app such as ZORVYQ itself; the marker never becomes a ZORVYQ activity record. Privacy edits restart the owned watcher with updated filters. Consequently the managed watcher deliberately provides no window titles even if ZORVYQ's optional safe-title setting is on. Independently configured watchers can supply optional safe titles; their upstream privacy behavior must be reviewed separately.

## Local lifecycle

`LocalRuntime` starts the verified server with `--host 127.0.0.1 --port 5600`, private XDG directories under the activity database directory's `activitywatch/`, umask 0077, no environment proxies, and no captured child output. A responsive existing server is reused; identified independent window watchers are not duplicated. Only owned child handles are terminated. An unresponsive foreign listener can prevent startup; ZORVYQ does not kill it.

The existing single-consumer lock serializes GUI and optional user-service ingestion. Activity polling waits three seconds between bounded requests; metrics sample at most once a minute; GUI snapshot display refreshes once a second without inference. ON requires recent valid foreground and AFK heartbeats (15-second freshness). Last observed elapsed time is displayed, rather than extrapolating into a watcher outage. Unknown apps remain unavailable; idle state is shown separately.

Pause/disable discards in-flight reads at the consent boundary and prevents further ZORVYQ writes. An owned in-process watcher stops before the control returns; a separately running approved background consumer observes database changes on its next bounded polling cycle and stops its owned runtime. To stop that entire service immediately use the service command below. External watchers/extensions have their own lifecycle and history.

## Firefox

Review/install the [official Firefox watcher](https://addons.mozilla.org/en-US/firefox/addon/aw-watcher-web/), linked by the [official watcher repository](https://github.com/ActivityWatch/aw-watcher-web), using Firefox's normal permission dialog. ZORVYQ does not install or activate it. Leave **Run in Private Windows** disabled. Review/configure upstream browser exclusions before collection: the extension stores its own URLs/titles in ActivityWatch independently of ZORVYQ's minimized copy.

In ZORVYQ, separately enable Firefox monitoring and approve exact domains. Domain matching permits subdomains. Titles and sanitized URL paths require additional opt-ins; query strings, fragments, URL credentials and token-like paths are excluded. Authentication/private/sensitive pages are rejected; unknown incognito state is rejected. Browser totals intersect actual Firefox foreground and not-AFK intervals. Browser presence alone never proves website activity. Custom website categories are available through **Set website category**.

Expected API types: `currentwindow`, `afkstatus`, and `web.tab.current` with a Firefox bucket identifier. Exactly one foreground/AFK source is required; multiple sources fail closed. Private-state flags, actual identifiers and supported event schemas need owner verification with the installed extension.

## Startup and background operation

**Start Monitoring at Login** defaults OFF. It uses the working GUI startup without changing its desktop file; when enabled, previously approved collection starts as the GUI opens. The connection retries while desktop services become ready.

**Independent background monitoring** is a separate explicit confirmation. It writes only the reviewed `~/.config/systemd/user/zorvyq-awareness.service`, imports four named desktop environment values, runs `daemon-reload`, and enables/starts that user service. Its confirmation includes login operation and enables Start Monitoring at Login visibly. No system service, lingering, firewall changes, or unrelated startup edits occur. Changing this switch runs through a QThread, with GUI updates delivered by Qt signals. A differing pre-existing unit is refused.

The service is tied to `graphical-session.target`, runs the same permission-bound consumer without Qt or models, uses the same SQLite lock, stops at logout, and keeps recording after GUI close only when enabled. User-systemd IPAddressDeny/Allow directives provide additional isolation where supported; they are not a verified kernel firewall guarantee. Startup OFF makes a newly launched daemon exit without monitoring. Turning off the background option stops/disables the service; GUI-only approved collection may continue.

## Commands and troubleshooting

Use `bin/zorvyq`, then Settings → Activity & Privacy → Start monitoring now / Stop monitoring / Pause / Resume. No CLI command silently grants monitoring consent.

```bash
.venv/bin/python -B -m zorvyq.awareness status
.venv/bin/python -B -m zorvyq.awareness pause
.venv/bin/python -B -m zorvyq.awareness resume
.venv/bin/python -B -m zorvyq.awareness disable
# Only after independent background opt-in has installed the unit:
systemctl --user status zorvyq-awareness.service
systemctl --user stop zorvyq-awareness.service
systemctl --user start zorvyq-awareness.service
systemctl --user disable --now zorvyq-awareness.service
```

CLI status initializes/migrates the activity store if needed; it does not start a watcher. Resume removes pause but grants no additional scopes. Disable switches off both application collection and stored metrics. Settings remains the consent entry point.

**Service unavailable:** confirm the verified binaries, port availability, local server configuration and file permissions. **Watcher unavailable:** check GNOME extension compatibility/activation and IdleMonitor, app allowlist, stale or ambiguous sources. **Browser unavailable:** verify the official add-on, Firefox foreground, browser opt-in, approved domain and explicit non-private event metadata. Unsupported/authenticated ActivityWatch APIs fail closed; no credential discovery is attempted. Rate/size saturation is reported unavailable, not accepted as a complete total.

## Updates, removal, and offline use

Update into a separate versioned runtime, verify new official archive metadata and checksums, review dependencies/schemas/CLI flags, update the manifest and rerun tests/server smoke check before selecting it. Do not execute upstream `make install`/`uninstall` in ZORVYQ's environment. Upstream source checkouts/binaries/archives are ignored by Git; the provenance manifest and integration code are tracked candidates. No automatic update task is installed.

To uninstall, first disable monitoring and metrics, turn off independent background monitoring (or disable/stop its user service), then remove only the reviewed user-service file and run `systemctl --user daemon-reload`. Disable/remove the GNOME and Firefox extensions in their own UIs if desired. Remove the isolated third-party directories when no owned process uses them. Retain the activity SQLite database and upstream data unless intentionally clearing them; no uninstall step here automatically deletes history.

Once binaries/extensions are installed, collection and deterministic queries require only local OS facilities and loopback HTTP. Optional summaries require an already-installed local Ollama model. Installation, extension updates and visiting websites can use the internet; independently operated upstream components and web UI have not had all dependency network behavior audited. Automated offline checks deny DNS/non-loopback Python sockets with synthetic sources; this is not a physical disconnected desktop acceptance test.
