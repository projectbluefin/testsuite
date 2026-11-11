---
name: display-config
description: "MIME, display, and session configuration in containerized tests."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Display Config

## xdg-mime in container mode

`_xdg_mime_default(mime_type)` in smoke steps.py runs `xdg-mime query default`
to check MIME handler registration. When `_IN_CONTAINER` is True (runner
container SSHing into the VM), `xdg-mime` is not installed on the container
host — it lives in the Bluefin VM. Always route through `_ssh_run` in that
case.

**Critical**: SSH sessions do NOT inherit the GNOME user session `XDG_DATA_DIRS`.
Flatpak apps (Firefox, Papers, Loupe, Showtime) register MIME handlers under
`/var/lib/flatpak/exports/share/applications/`. Without this path in
`XDG_DATA_DIRS`, `xdg-mime query default` returns empty for Flatpak MIME types.

**Keep allowlists synced to the OOTB set**: the `DOCUMENT_VIEWERS` /
`IMAGE_VIEWERS` / `TEXT_EDITORS` / `VIDEO_PLAYERS` sets in smoke `steps.py`
must match what `flatpak_permissions.feature` says the image actually ships.
Bluefin ships `org.gnome.Showtime` as its OOTB video player — a stale
allowlist (e.g. Celluloid-only) blocks the matching mimeapps.list default in
projectbluefin/common from ever passing.

Always set `XDG_DATA_DIRS` explicitly in the SSH call:

```python
from app_support import _IN_CONTAINER, _ssh_run
if _IN_CONTAINER:
    result = _ssh_run(
        "XDG_DATA_DIRS=/var/lib/flatpak/exports/share"
        ":/home/bluefin-test/.local/share/flatpak/exports/share"
        ":/usr/local/share:/usr/share "
        f"xdg-mime query default {mime_type}"
    )
    return result.stdout.strip()
```

`xdg-mime query default` does NOT require a running D-Bus session.

## Power panel on hardware-free VMs

The smoke tag `@requires_vm_power_supply` skips before the Settings Background
only when the DUT is a VM (`systemd-detect-virt --vm`) and its
`/sys/class/power_supply` directory is empty. The probe uses `_run_host`, not
runner-local sysfs. Bare metal and VMs exposing any power supply retain the
normal accessibility assertion; probe failures fail rather than skip.

In testsuite#1153, both attempts of run 43010304130 show Settings opening
`gnome-control-center power`, followed by a 25-second D-Bus activation timeout
for `org.freedesktop.UPower.PowerProfiles`. The service starts only near shutdown;
the captured serial logs do not show a Settings coredump. Boot also reports an
empty power-supply directory. This supports a narrow hardware-free VM exclusion,
not a claim that Settings crashes on physical hardware or that all Power panel
failures are harmless. Do not raise the AT-SPI timeout or quarantine the whole
feature. Revisit this exclusion when the VM's power-service activation is fixed;
a successful Power panel run on a hardware-free VM is the removal evidence.
