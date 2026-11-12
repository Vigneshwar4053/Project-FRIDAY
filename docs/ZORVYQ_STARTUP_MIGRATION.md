# ZORVYQ startup migration

## Read-only findings — 2026-10-31

The live checkout is `/home/vigneshwar/Projects/zorvyq`. The supplied historical
`/home/vigneshwar/Projects/FRIDAY` path does not exist. No directory was moved in
this extension.

The identified graphical-login cause is
`/home/vigneshwar/.config/autostart/friday.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=FRIDAY AI
Comment=Start FRIDAY automatically after login
Path=/home/vigneshwar/Projects/FRIDAY
Exec=/home/vigneshwar/Projects/FRIDAY/.venv/bin/python -B -m friday.main --adaptive
Terminal=true
X-GNOME-Autostart-enabled=true
```

This entry requests the terminal CLI after graphical login. Its stale path may
currently prevent successful startup; a real login was not performed.
`~/.local/bin/friday-start.sh` also explicitly runs `gnome-terminal --title="FRIDAY
AI" -- bash -lc ...` against the old checkout. No inspected login entry references
that helper. It was left intact.

Read-only text matching of `.bashrc`, `.profile`, user autostart entries,
`~/.config/systemd/user`, installed application entries and local launch scripts
found no additional FRIDAY shell-login or user-service trigger. Optional
`.bash_profile`, `.zshrc`, `.bash_login`, `.xprofile`, `.xsession`, `.xsessionrc`
and GNOME saved-session directory are absent. This is an inventory of inspected
locations, not a claim about every possible system-wide trigger. `.env` was not read.

The installed `~/.local/bin/zorvyq` still points to the missing FRIDAY checkout.
The installed desktop entry already uses `Terminal=false`, but needs its wrapper
reinstalled from the current checkout. No installed launch/startup files were
modified during this extension.

## Launch now and proposed installation

Run `/home/vigneshwar/Projects/zorvyq/bin/zorvyq` (for example via Ubuntu's Run
Application dialog). It uses this checkout's `.venv/bin/python -B -m zorvyq`;
manual virtual-environment activation is unnecessary. It opens Qt, has no startup
inference, and shows graphical startup/dependency errors when Qt or Zenity can run.
Missing display/plugin failures before Qt initializes can still need host repair.

After explicit owner approval, repair user-local application metadata with:

```sh
/home/vigneshwar/Projects/zorvyq/.venv/bin/python -B /home/vigneshwar/Projects/zorvyq/scripts/install_zorvyq_desktop.py
```

This replaces only `~/.local/bin/zorvyq`, the ZORVYQ application desktop entry,
and the ZORVYQ icon. Back up those existing files before installation if retaining
the old path is desired. It installs no packages and changes no autostart files.
The installer supports `--prefix /tmp/zorvyq-launcher-review` for isolated review.
The isolated installer and desktop metadata validation are tested automatically.

## Login behavior and approval

Settings → **Launch ZORVYQ when I log in** reflects enabled ZORVYQ or legacy login
behavior. **Replace legacy login startup with ZORVYQ…** asks approval for the exact
legacy location and the graphical replacement. The legacy behavior remains until
approval; ordinary terminal opening never invokes this setting.

Before enabling login startup, repair and manually test the installed GUI launcher.
The backend preflights desktop metadata before disabling legacy startup, checks a
fingerprint of both entries, refuses unknown legacy commands and symlink files,
and preserves `friday.desktop.zorvyq-backup`. Repeated toggles use one managed entry:
`~/.config/autostart/com.zorvyq.ZORVYQ.desktop`. OFF preserves a disabled entry;
ON replaces that same entry. No unrelated startup service is modified.

To reverse an approved migration, `Startup.restore_legacy(approved=True)` disables
the managed GUI entry and restores the byte-exact backup only if the legacy file
still matches this implementation's disabled version. Changes made by another
application require manual review. The backup is never deleted. Ordinary I/O
failures attempt rollback; abrupt power failure between separate file replacements
cannot be made transactional across both desktop files.

## Owner acceptance

1. Approve repair of installed ZORVYQ metadata, then click ZORVYQ in Applications.
2. Confirm the dashboard opens without Terminal, inference, audio or application reopening.
3. Close while idle; during work, wait for bounded completion before closing.
4. Separately approve replacing exactly the identified FRIDAY autostart entry.
5. Log out and back in. Confirm one GUI opens and the legacy terminal does not.
6. Open Ubuntu Terminal normally and confirm its behavior is unchanged.
7. Toggle login startup OFF, repeat login, then ON if desired; confirm no duplicates.

Mocked temporary-home tests cover identification, approval fingerprints, preflight,
backup/restoration, ON/OFF/ON and isolated desktop installation. They do not certify
an actual Ubuntu login. See `ZORVYQ_PHASE2A_ADDITIONAL_REPORT.md` for test results.
