---
name: uefi-boot
version: "1.0"
last_updated: "2026-10-28"
id: uefi-boot
one_line_purpose: Add or debug UEFI/OVMF reboot tests and design desktop first-login qualification.
entry_point: docs/skills/test-authoring/uefi-boot/SKILL.md
category: test-authoring
mcp_compliance_level: partial
status: active
dependencies: []
tags: [uefi, ovmf, boot]
description: "UEFI/OVMF reboot testing and desktop first-login qualification guidance. Load when adding or debugging UEFI boot paths in e2e workflows, or designing firmware-boot and native GIS/GDM first-login qualification."
metadata:
  type: pattern
  audience: agents
  maturity: stable
---
# UEFI Boot via OVMF + systemd-boot

Load when: working on migration tests that require VM reboots, modifying the QEMU boot pipeline, debugging UEFI/systemd-boot issues in CI, or designing firmware-boot / desktop first-login qualification (see the [desktop qualification contract](references/desktop-first-login.md)).

## Why UEFI boot matters

The existing `e2e.yml` uses **direct kernel boot** (`-kernel/-initrd/-append`). This extracts vmlinuz and initramfs at disk-setup time and passes them directly to QEMU. The VM always boots the same kernel — rebooting after `bootc switch` still boots the original deployment because QEMU re-uses the same kernel args.

Migration tests need the VM to boot the **new deployment** after `bootc switch` + reboot. UEFI boot via OVMF + systemd-boot solves this: systemd-boot reads BLS (Boot Loader Specification) entries from the disk and picks the highest-priority entry, which is the staged deployment after a switch.

## Disk layout (bootc install to-disk --bootloader systemd)

| Partition | Type | Mount point | Contents |
|-----------|------|-------------|----------|
| p1 | EFI System | `/boot/efi` | `EFI/BOOT/BOOTX64.EFI` (systemd-boot fallback binary), `EFI/systemd/systemd-bootx64.efi` |
| p2 | xbootldr | `/boot` | `loader/loader.conf`, `loader/entries/*.conf` (BLS entries), kernel + initramfs per deployment |
| p3 | Linux filesystem (ext4) | `/` | ostree root (deployments, /var, etc.) |

BLS entries live in **p2** (`/boot/loader/entries/`), not p1.

## OVMF variant

Use **`OVMF_CODE_4M.fd`** (4MB pflash variant). The standard 2MB `OVMF_CODE.fd` works for simple UEFI boot but systemd-boot on Fedora writes more EFI variables than fit in the 2MB variable store.

On ubuntu-latest (GHA runner), install the `ovmf` package:
```bash
sudo apt-get install -y --no-install-recommends ovmf
```

Files:
- `/usr/share/OVMF/OVMF_CODE_4M.fd` — read-only firmware code
- `/usr/share/OVMF/OVMF_VARS_4M.fd` — writable variable store template

## QEMU pflash flags

```bash
# Copy VARS to a writable per-VM location (pflash needs read-write access).
cp /usr/share/OVMF/OVMF_VARS_4M.fd ./ovmf_vars.fd

sudo qemu-system-x86_64 \
  -machine  q35,accel=kvm \
  -cpu      host \
  -m        4096 \
  -smp      4 \
  -drive    if=pflash,format=raw,unit=0,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
  -drive    if=pflash,format=raw,unit=1,file=./ovmf_vars.fd \
  -drive    if=none,id=disk,file=disk.raw,format=raw,cache=unsafe,aio=threads,discard=unmap \
  -device   virtio-blk-pci,drive=disk \
  ...
```

Key points:
- `unit=0` (read-only) = firmware code
- `unit=1` (writable) = EFI variable store — must be a per-VM copy, not the system template
- OVMF with empty VARS auto-detects the ESP and launches `EFI/BOOT/BOOTX64.EFI`
- No manual boot entry or loader.conf tweaks needed

## What changes vs direct kernel boot

| Aspect | Direct kernel boot | UEFI boot (OVMF) |
|--------|-------------------|-------------------|
| QEMU flags | `-kernel vmlinuz -initrd initramfs.img -append "root=UUID=..."` | `-drive if=pflash,...` (two pflash drives) |
| Kernel args | Passed via `-append` | Written in BLS entries by bootc |
| Reboot behavior | Always boots same kernel | systemd-boot picks highest-priority BLS entry |
| Extra packages | None | `ovmf` (apt) |
| Boot time | Faster (~30s to SSH) | Slightly slower (~45-60s — UEFI firmware init + systemd-boot menu timeout) |
| Kernel extraction | Required (copy vmlinuz/initramfs from disk) | Not required (systemd-boot reads from xbootldr) |
| ostree boot.N symlink workaround | Required | Not required (bootc sets up BLS entries correctly) |

## loader.conf timeout

systemd-boot defaults to a short menu timeout. In CI, set `timeout 0` in `loader/loader.conf` to skip the boot menu entirely (no human interaction in CI). If `loader.conf` is missing, systemd-boot auto-boots the default entry after a brief pause.

## bootc switch + reboot cycle

After `bootc switch <target>`:
1. bootc pulls the target image layers
2. bootc stages a new ostree deployment
3. bootc writes a new BLS entry in `/boot/loader/entries/` with a higher sort key
4. On reboot, systemd-boot picks the new BLS entry → the new deployment boots
5. The previous deployment becomes the rollback target

This is the core mechanism that migration tests validate.

## Known limitations

- **Boot time is longer** — OVMF firmware initialization adds ~10-15s over direct kernel boot. The SSH wait deadline should be 600s for initial boot (vs 900s for direct boot, which needs extra time for different reasons).
- **--bootloader flag requires bootc >= 0.1.13** — older images fail. Always probe `--help` before using.
- **Service masking via kernel args is lost** — with direct boot, services are masked via `systemd.mask=...` in `-append`. With UEFI boot, masking must be done on-disk (symlink to `/dev/null` in the deployment's `/etc/systemd/system/`) — which `e2e.yml` already does.
- **selinux=0 kernel arg is lost** — must be set in BLS entries or on-disk config instead. For migration tests with SELinux enforcing (Epic E04), this is actually correct behavior.

## GRUB 2 vs systemd-boot Unified Virtualization Strategy

This strategy is for migration testing. Installing a replacement bootloader
does not qualify the boot path shipped to desktop users. For firmware boot
and first-login claims, use the proposed
[desktop qualification contract](references/desktop-first-login.md); its
image eligibility and hosted evidence gates remain separate from smoke and
migration results.

Modern bootc/ostree images write Boot Loader Specification (BLS) entries (`/boot/loader/entries/*.conf`) regardless of whether the physical distribution targets GRUB 2 (like Bluefin / Bluefin LTS) or systemd-boot (like Dakota).

For migration-only QEMU experiments, use loopback installation with
`--bootloader systemd`.
*   This installs systemd-boot onto the loopback disk's ESP for *all* image variants.
*   systemd-boot reads the BLS entries and successfully bootc-upgrades, bootc-switches, and reboots inside the QEMU VM.
*   This avoids GRUB installation complexity for the migration experiment. It does not prove that the image's supported GRUB installation or firmware handoff works.

## Spike workflow

The spike is implemented in `.github/workflows/spike-uefi-boot.yml`. Run it via Actions → "Spike: UEFI Boot" → Run workflow. It:
1. Installs `ublue-os/bluefin:stable` to disk with `--bootloader systemd`
2. Inspects the ESP and BLS entries (answers spike questions #1-2)
3. Boots via OVMF pflash (answers questions #3-4)
4. SSHs in, runs `bootc switch` to `projectbluefin/bluefin:stable`
5. Reboots and confirms the new deployment is active (answers question #5)
