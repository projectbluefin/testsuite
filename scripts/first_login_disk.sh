#!/usr/bin/env bash
# Prepare a disk for the first-login probe (#1179, design in
# docs/skills/test-authoring/uefi-boot/references/desktop-first-login.md).
#
# Usage: first_login_disk.sh IMAGE@sha256:DIGEST OUTDIR PUBKEY_FILE
#
# Unlike e2e.yml's smoke disk, this one must reach the image's real first-boot
# journey:
#   - the image's own bootloader is installed (no --bootloader override, and a
#     failed bootloader step is fatal: there is no -kernel fallback);
#   - no regular user, no GDM auto-login, no SSH user;
#   - the only access is a per-run, key-only root SSH key, read by sshd from
#     /etc/ssh/ci-authorized-keys (decided on #1026). Root is uid 0, so GNOME
#     Initial Setup still sees no regular user.
# Writes OUTDIR/disk.raw plus evidence: bootc-install.log, esp.txt,
# disk-users.txt and disk.json. Prints nothing secret: only the public key is
# written to the disk.
set -euo pipefail

IMAGE=${1:?image@sha256:digest}
OUTDIR=${2:?output directory}
PUBKEY=${3:?public key file}
[[ "$IMAGE" == *@sha256:* ]] || { echo "::error::image must be digest-pinned: $IMAGE"; exit 2; }
[[ -s "$PUBKEY" ]] || { echo "::error::public key file missing: $PUBKEY"; exit 2; }
mkdir -p "$OUTDIR"
OUTDIR=$(cd "$OUTDIR" && pwd)
DISK="$OUTDIR/disk.raw"
ROOTMNT=$(mktemp -d)
ESPMNT=$(mktemp -d)
LOOP=""

cleanup() {
  sudo umount "$ESPMNT" 2>/dev/null || true
  sudo umount "$ROOTMNT" 2>/dev/null || true
  [[ -n "$LOOP" ]] && sudo losetup -d "$LOOP" 2>/dev/null || true
  rmdir "$ROOTMNT" "$ESPMNT" 2>/dev/null || true
}
trap cleanup EXIT

fallocate -l 40G "$DISK"

# Kernel arguments: a serial console for evidence, and no interactive
# systemd-firstboot prompt on the console. Neither changes GDM or GNOME
# Initial Setup. Older bootc lacks --karg; then the image's defaults stand.
KARGS=()
if sudo podman run --rm --quiet "$IMAGE" bootc install to-disk --help 2>&1 | grep -q -- "--karg"; then
  KARGS=(--karg "console=ttyS0,115200" --karg "systemd.firstboot=no")
fi

INSTALLED=false
for ATTEMPT in 1 2 3; do
  echo "bootc install to-disk: attempt $ATTEMPT/3"
  set +e
  sudo podman run --rm --privileged --pid=host \
    --security-opt label=type:unconfined_t \
    -v /var/lib/containers:/var/lib/containers -v /dev:/dev -v "$OUTDIR:/data" \
    "$IMAGE" bootc install to-disk --via-loopback /data/disk.raw \
      --filesystem ext4 --wipe "${KARGS[@]}" 2>&1 | tee "$OUTDIR/bootc-install.log"
  RC=${PIPESTATUS[0]}
  set -e
  if [[ $RC -eq 0 ]]; then INSTALLED=true; break; fi
  # Retry only the udev race e2e.yml documents ("root partition 3 has type
  # <none>"); any other failure, including the bootloader step, is final.
  grep -q "has type <none>" "$OUTDIR/bootc-install.log" || break
  for stale in $(sudo losetup -n -O NAME -j "$DISK"); do sudo losetup -d "$stale" || true; done
  sudo udevadm settle || true
done
if [[ "$INSTALLED" != true ]]; then
  echo "::error title=unreachable::bootc install to-disk failed (exit $RC); the image's own loader could not be installed, so this disk cannot reach the first-boot journey. See bootc-install.log."
  printf '{"verdict": "unreachable", "reason": "bootc install to-disk failed", "exit": %d}\n' "$RC" > "$OUTDIR/disk.json"
  exit 1
fi

LOOP=$(sudo losetup -f --show -P "$DISK")
sudo udevadm settle || true
ESP="" ROOT=""
for part in "${LOOP}"p*; do
  case "$(sudo blkid -s TYPE -o value "$part" 2>/dev/null || true)" in
    vfat) ESP=$part ;;
    ext4|xfs)
      if sudo mount "$part" "$ROOTMNT"; then
        if [[ -d "$ROOTMNT/ostree/deploy" ]]; then ROOT=$part; else sudo umount "$ROOTMNT"; fi
      fi ;;
  esac
  [[ -n "$ROOT" && -n "$ESP" ]] && break
done
[[ -n "$ESP" && -n "$ROOT" ]] || { echo "::error::could not find the ESP and ostree root on $LOOP"; exit 1; }

# Checkpoint 0 evidence: what the image's installer put on the ESP.
sudo mount -o ro "$ESP" "$ESPMNT"
(cd "$ESPMNT" && sudo find . -type f | sort) > "$OUTDIR/esp.txt"
sudo umount "$ESPMNT"
grep -qi '^./EFI/BOOT/BOOTX64.EFI$' "$OUTDIR/esp.txt" || {
  echo "::error title=unreachable::no EFI/BOOT/BOOTX64.EFI on the ESP; firmware has nothing to hand off to"
  printf '{"verdict": "unreachable", "reason": "no UEFI fallback loader on the ESP"}\n' > "$OUTDIR/disk.json"
  exit 1
}

STATEROOT="$ROOTMNT/ostree/deploy/default"
: > "$OUTDIR/disk-users.txt"
LABEL_LIST=$(mktemp)
for DEP in "$STATEROOT"/deploy/*/; do
  DEP=${DEP%/}
  [[ -d "$DEP/etc" ]] || continue
  sudo mkdir -p "$DEP/etc/ssh/sshd_config.d"
  # 00- sorts before the image's drop-ins; AuthorizedKeysCommand avoids any
  # home directory or userdb dependency (same reasoning as e2e.yml).
  printf 'PermitRootLogin prohibit-password\nPubkeyAuthentication yes\nPasswordAuthentication no\nAuthorizedKeysCommand /bin/cat /etc/ssh/ci-authorized-keys\nAuthorizedKeysCommandUser root\n' \
    | sudo tee "$DEP/etc/ssh/sshd_config.d/00-ci-root.conf" >/dev/null
  sudo install -m 644 -o root -g root "$PUBKEY" "$DEP/etc/ssh/ci-authorized-keys"
  # The image doesn't enable sshd; enable it and pre-generate host keys, as
  # e2e.yml does. Only the probe's SSH depends on this, not the desktop.
  sudo mkdir -p "$DEP/etc/systemd/system/multi-user.target.wants"
  sudo ln -sf /usr/lib/systemd/system/sshd.service \
    "$DEP/etc/systemd/system/multi-user.target.wants/sshd.service"
  sudo ssh-keygen -A -f "$DEP" >/dev/null
  printf '%s\n' "$DEP/etc/ssh/sshd_config.d/00-ci-root.conf" "$DEP/etc/ssh/ci-authorized-keys" \
    "$DEP/etc/systemd/system/multi-user.target.wants/sshd.service" >> "$LABEL_LIST"
  sudo find "$DEP/etc/ssh" -maxdepth 1 -name 'ssh_host_*' | tee -a "$LABEL_LIST" >/dev/null
  # Regular users the disk would start with (names and uids only; no shadow).
  for passwd in "$DEP/etc/passwd" "$DEP/usr/lib/passwd"; do
    [[ -f "$passwd" ]] && sudo awk -F: -v src="${passwd#"$DEP"}" '$3 >= 1000 && $3 < 60000 {print src ": " $1 " " $3}' "$passwd"
  done >> "$OUTDIR/disk-users.txt"
done

# Label the added files with the image's own policy, as e2e.yml does.
DEP=$(sudo find "$STATEROOT/deploy" -mindepth 1 -maxdepth 1 -type d | head -1)
POLICY=$(sudo awk -F= '$1=="SELINUXTYPE"{print $2}' "$DEP/etc/selinux/config" 2>/dev/null || true)
if [[ -n "$POLICY" ]]; then
  LISTDIR=$(mktemp -d)
  sed "s#^$ROOTMNT#/harness/root#" "$LABEL_LIST" > "$LISTDIR/list"
  sudo podman run --rm --privileged --network none --security-opt label=disable \
    -v "$ROOTMNT:/harness/root" -v "$LISTDIR:/harness/list:ro" \
    "$IMAGE" setfiles -m -F -r "/harness/root${DEP#"$ROOTMNT"}" \
      -f /harness/list/list "/harness/root${DEP#"$ROOTMNT"}/etc/selinux/$POLICY/contexts/files/file_contexts"
fi

python3 - "$IMAGE" "$OUTDIR" "$(basename "$DEP")" "${#KARGS[@]}" <<'PY'
import json, sys
image, out, deploy, kargs = sys.argv[1:5]
users = [l for l in open(f"{out}/disk-users.txt").read().splitlines() if l.strip()]
json.dump({"verdict": "prepared", "image": image, "deployment": deploy,
           "kargs": ["console=ttyS0,115200", "systemd.firstboot=no"] if int(kargs) else [],
           "regular_users": users,
           "loader": "EFI/BOOT/BOOTX64.EFI present"}, open(f"{out}/disk.json", "w"), indent=2)
PY
echo "Disk prepared: $(jq -c . "$OUTDIR/disk.json" 2>/dev/null || cat "$OUTDIR/disk.json")"
