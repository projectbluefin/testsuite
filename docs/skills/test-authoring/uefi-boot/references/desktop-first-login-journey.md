---
name: desktop-first-login-journey
description: "Load when running, changing or reviewing the first-boot journey workflow: page recognition, cases, controlled failures and credential handling (#1180)."
metadata:
  type: reference
  audience: agents
  maturity: draft
---

# First-boot journey (#1180)

Step 3 of the [desktop qualification contract](desktop-first-login.md), on the
image and page order its admission record names, against the
[acceptance cases](desktop-first-login-cases.md).

The same workflow now runs the whole journey, one job per case, each on its
own fresh disk and variable store. `scripts/first_login_journey.py` replaces
the probe's key-press check and keeps its first two checkpoints:

1. **Loader:** a kernel on serial after the firmware's handoff.
2. **Initial Setup:** its process is the session and the disk has no
   regular user.
3. **Pages:** the admission record's order, by monitor key presses only.
   Before each action the driver waits up to 120 s for the page, recognised
   by the title GNOME Initial Setup 51.1 puts in its header bar ("Welcome",
   "Typing", "Network", "Privacy", "Time Zone", "About You", "Password",
   "Setup Complete"). Network may be absent (it hides itself when the guest
   is online); every other page is required, and a later page arriving
   first fails as `required-page-missing`. Nothing else on screen fails as
   `unrecognized-screen` at the deadline. On each page it focuses the widget
   it needs with Tab, checks it is focused, then types or presses Return:
   Next (it must be sensitive), the time zone search when no location is
   set yet, the full name `Firstboot`, the password twice, and the summary's
   start button.
4. **Account and hand-off:** exactly one new regular user, uid ≥ 1000, in
   `wheel` (GIS 51.1 creates the first account as an administrator), an
   active graphical session for it, and its
   `~/.config/gnome-initial-setup-done`.
5. **Login:** reboot over root SSH, no session for the user before login
   (no auto-login), then select the user at GDM's greeter, type the
   password and get an active graphical session for that uid.

Pages are read by `scripts/first_login_ui_state.py`, sent to the guest
over the per-run root key. It finds the target process (Initial Setup, or
GNOME Shell run by a `gdm*` user for the greeter), drops to that process's
own uid and session bus, and reads its accessibility tree: names, roles and
states of showing widgets only. It never reads entry text, sends input or
authenticates as anyone. This is a read of guest state over the management
channel decided on #1026, not a second input path.

**Controlled failures**, each expected to fail with exactly its named
failure (the job passes only then):

| Case | Fixture | Expected failure |
|---|---|---|
| `wrong-password` | The supported disk; a different random password at the greeter | `authentication` |
| `missing-page` | The disk's `/etc/gnome-initial-setup/vendor.conf` also skips privacy (`skip=software;privacy`) | `required-page-missing` |
| `no-loader` | The ESP's `EFI` directory removed after the loader was checked | `loader-handoff` |

**Credentials:** the password is generated per run in the driver's memory
(letters and digits, so each character has a monitor key name). It is never
printed, written or passed as an argument. No frame is kept from the
account, password or summary pages or of the greeter's password prompt.
Before exit the driver copies the serial log and every boot's journal into
the results and scans every retained file for the password; a hit deletes
the evidence and fails the run as `credential-exposure`.

Dispatch with `cases` (a JSON list) to run a subset, for example
`gh workflow run first-login-probe.yml -f cases='["happy"]'`.

