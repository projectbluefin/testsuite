---
name: dakota-os
description: "Dakota OS shipping-contract coverage map: load when editing tests/common/features/dakota_os.feature."
metadata:
  type: reference
  audience: agents
  maturity: stable
---

# Dakota OS coverage (common suite)

`tests/common/features/dakota_os.feature` is `@common @dakota_only`; the common
`before_scenario` hook skips it on non-Dakota images. It uses only the shared
SSH steps (`tests/shared/ssh_steps.py`) plus `Last command exits with non-zero status`.

Verified against `projectbluefin/dakota` `origin/testing` @ `7da52839` and image
`ghcr.io/projectbluefin/dakota@sha256:6e8f0d96…` (label revision `7da52839`).

| Scenario | Shipping source |
|---|---|
| os-release identity, NAME-first ordering, variant name/ref | `include/os-release.yml` |
| booted image ref + image-info.json tag | `files/firstboot/ublue-booted-image-sync` |
| sudo-rs, secure_path, PAM | `elements/bluefin/sudo-rs.bst`, `sudo-linuxbrew-path.bst` |
| uupd polkit (live `pkcheck`) | `elements/bluefin/uupd.bst` → `/etc/polkit-1/rules.d/uupd.rules` |
| NetworkManager wheel rule (gjs-evaluated) | `files/polkit/org.freedesktop.NetworkManager.rules` |
| Tailscale / ChairLift polkit actions | `tailscale-setup.bst`, `chairlift.bst` |
| zswap kargs + sysctls, zram off, swapfile | `zswap-config.bst`, `swapfile.bst` |
| `/home` `/root` `/snap` bind mounts | `bindmounts.bst` |
| `/var/home` passwd migration | `migrate-var-home-passwd.bst` (harness creates a legacy `/var/home/bluefin-test` entry) |
| erofs loop hidden from UDisks (attaches a temporary erofs loop) | `files/udev/90-hide-composefs-loop.rules` |
| libvirt / virtiofsd / QEMU, daemons preset-disabled | `virtualization.bst`, `libvirt.bst`, `files/libvirt/80-libvirt.preset` |
| duplicate launchers removed (#1829) | `elements/bluefin/common.bst` |

## Known product failures

- `duplicate common launchers are removed` fails on `7da52839`: `common.bst`
  removes `%{install-root}%{prefix}/usr/share/applications/…` (`/usr/usr/…`), so
  `system-update.desktop`, `discourse.desktop`, `documentation.desktop` still ship.
- `legacy /var/home passwd entries are migrated to /home` fails: the fast path in
  `files/migrate-var-home-passwd/bluefin-migrate-var-home-passwd` greps
  `:(/var/home/|/var/roothome)(:|$)`, which only matches a bare `/var/home/`
  field, so `/var/home/<user>` entries exit before the rewrite loop.

## Lane notes

- The e2e lane boots with the legacy ostree bind mount, not composefs, so no
  composefs erofs loop exists; the UDisks scenario attaches its own erofs loop.
- Published `/etc/sudoers.d/*` are mode 0600 although the source chmods 0440;
  the scenario asserts root ownership and no group/other write.

## Not covered on the fast lane

- zswap runtime state: the e2e lane direct-boots its own cmdline, so
  `kargs.d` is never applied; only the shipped kargs file is asserted.
- x86-64-v3 baseline: no image label, os-release field, or file records it.
- Secure Boot, systemd-boot timeout, kexec-disable: need UEFI disk boot.
