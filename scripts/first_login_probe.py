#!/usr/bin/env python3
"""First-login probe (#1179): checkpoints on a running first-boot VM.

The VM was booted by the workflow from a disk prepared by
scripts/first_login_disk.sh, through OVMF and the disk's own loader (no
-kernel). This script observes it through three host-side channels only:
the serial log, the QEMU monitor (framebuffer dumps and key presses), and the
per-run root SSH key. It never authenticates as a desktop user.

Checkpoints (docs/skills/test-authoring/uefi-boot/references/desktop-first-login.md):
  1. firmware handed off to the disk's loader (serial);
  2. GNOME Initial Setup is the running session (root SSH: its process and
     the GDM session), with framebuffer evidence;
  3. a monitor key press changes the Initial Setup page (frames differ).
Writes OUTDIR/verdict.json with the last checkpoint reached.

Usage: first_login_probe.py OUTDIR MONITOR_SOCKET SERIAL_LOG SSH_KEY
Standard library only.
"""
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

LOADER_PATTERNS = (r"BdsDxe: (loading|starting) Boot\d+", r"GRUB", r"shim")
KERNEL_PATTERN = r"Linux version \d"


def wait_for_serial(serial, patterns, timeout, clock=time.monotonic, sleep=time.sleep):
    """Return the first serial line matching any pattern, or "" at the deadline."""
    deadline = clock() + timeout
    compiled = [re.compile(p) for p in patterns]
    while True:
        try:
            for line in Path(serial).read_text(errors="replace").splitlines():
                if any(c.search(line) for c in compiled):
                    return line.strip()
        except FileNotFoundError:
            pass
        if clock() >= deadline:
            return ""
        sleep(2)


def monitor(sock_path, command, timeout=10):
    """Send one human-monitor command and return its reply text."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(sock_path))
        s.recv(4096)  # greeting
        s.sendall((command + "\n").encode())
        time.sleep(0.5)
        try:
            return s.recv(65536).decode(errors="replace")
        except socket.timeout:
            return ""


def screendump(sock_path, ppm_path):
    """Dump the framebuffer to a PPM and return its bytes ("" if none)."""
    ppm = Path(ppm_path)
    ppm.unlink(missing_ok=True)
    monitor(sock_path, f"screendump {ppm}")
    for _ in range(20):
        if ppm.exists() and ppm.stat().st_size > 0:
            return ppm.read_bytes()
        time.sleep(0.25)
    return b""


def frames_differ(before, after, min_changed_bytes=64):
    """True when two same-sized PPM dumps differ in more than a few bytes."""
    if not before or not after or len(before) != len(after):
        return bool(before) != bool(after) or len(before) != len(after)
    changed = sum(1 for a, b in zip(before, after) if a != b)
    return changed >= min_changed_bytes


def ssh(key, command, timeout=20):
    """Run a command in the guest as root with the per-run key."""
    argv = ["ssh", "-i", str(key), "-p", "2222", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5", "root@127.0.0.1", command]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, ""
    return done.returncode, done.stdout.strip()


def wait_for_ssh(key, timeout, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while clock() < deadline:
        rc, _ = ssh(key, "true")
        if rc == 0:
            return True
        sleep(5)
    return False


def initial_setup_running(key):
    """Machine evidence that GNOME Initial Setup is the session on screen."""
    rc, procs = ssh(key, "pgrep -a -f gnome-initial-setup || true")
    _, sessions = ssh(key, "loginctl list-sessions --no-legend || true")
    _, users = ssh(key, "awk -F: '$3>=1000 && $3<60000 {print $1\" \"$3}' /etc/passwd")
    running = any("/gnome-initial-setup" in line and "copy-worker" not in line
                  for line in procs.splitlines())
    return {"running": running, "processes": procs[:2000], "sessions": sessions[:2000],
            "regular_users": [u for u in users.splitlines() if u.strip()]}


def run(outdir, sock, serial, key, boot_timeout=300, gis_timeout=420):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    verdict = {"checkpoint": 0, "passed": False}

    def finish(reason=""):
        verdict["reason"] = reason
        (out / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
        print("first-login probe: " + json.dumps(verdict), flush=True)
        return 0 if verdict["passed"] else 1

    # 1. Firmware -> the disk's own loader, then a kernel.
    loader = wait_for_serial(serial, LOADER_PATTERNS, boot_timeout)
    kernel = wait_for_serial(serial, (KERNEL_PATTERN,), boot_timeout)
    verdict.update(loader_line=loader, kernel_line=kernel)
    screendump(sock, out / "frame-boot.ppm")
    if not kernel:
        return finish("no kernel boot seen on serial within the deadline")
    verdict["checkpoint"] = 1

    # 2. GNOME Initial Setup is the running session.
    if not wait_for_ssh(key, gis_timeout):
        return finish("root SSH never came up")
    deadline = time.monotonic() + gis_timeout
    while True:
        evidence = initial_setup_running(key)
        if evidence["running"] or time.monotonic() >= deadline:
            break
        time.sleep(5)
    verdict["initial_setup"] = evidence
    if not evidence["running"]:
        return finish("GNOME Initial Setup never started")
    if evidence["regular_users"]:
        return finish("the disk already has a regular user; this is not the first-boot journey")
    verdict["checkpoint"] = 2

    # 3. A real key press changes the page (e.g. moves the language selection).
    time.sleep(10)  # let the first page settle before comparing frames
    before = screendump(sock, out / "frame-gis.ppm")
    for key_name in ("down", "down", "tab"):
        monitor(sock, f"sendkey {key_name}")
        time.sleep(1)
    after = screendump(sock, out / "frame-after-input.ppm")
    verdict["frames"] = {"before_bytes": len(before), "after_bytes": len(after)}
    if not frames_differ(before, after):
        return finish("a monitor key press did not change the Initial Setup frame")
    verdict["checkpoint"] = 3
    verdict["passed"] = True
    return finish()


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(run(*sys.argv[1:5]))
