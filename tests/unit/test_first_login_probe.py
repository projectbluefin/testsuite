"""First-login probe (#1179): the disk, the boot and the checkpoints.

The probe must reach the image's real first-boot journey: its own loader
through OVMF (never -kernel), no seeded user, no auto-login, and only a
per-run root key for observation. These tests pin that contract and the
probe's checkpoint logic without booting anything.
"""
import json
from pathlib import Path

import pytest
import yaml

from scripts import first_login_probe as probe

ROOT = Path(__file__).parents[2]
DISK_SCRIPT = (ROOT / "scripts/first_login_disk.sh").read_text()
WORKFLOW_TEXT = (ROOT / ".github/workflows/first-login-probe.yml").read_text()
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


# --- disk preparation ---------------------------------------------------------

def test_disk_uses_the_images_own_loader_and_never_falls_back_to_kernel_boot():
    code = [line for line in DISK_SCRIPT.splitlines() if not line.lstrip().startswith("#")]
    assert not any("--bootloader" in line for line in code)  # no systemd-boot substitution
    assert "title=unreachable" in DISK_SCRIPT
    assert "EFI/BOOT/BOOTX64.EFI" in DISK_SCRIPT


def test_disk_seeds_no_user_and_no_auto_login():
    for forbidden in ("AutomaticLogin", "useradd", "bluefin-test", "/var/home/"):
        assert forbidden not in DISK_SCRIPT


def test_disk_access_is_key_only_root():
    assert "PermitRootLogin prohibit-password" in DISK_SCRIPT
    assert "PasswordAuthentication no" in DISK_SCRIPT
    assert "AuthorizedKeysCommand /bin/cat /etc/ssh/ci-authorized-keys" in DISK_SCRIPT


def test_disk_requires_a_digest_pinned_image():
    assert '[[ "$IMAGE" == *@sha256:* ]]' in DISK_SCRIPT


# --- workflow -------------------------------------------------------------------

def _step(name):
    steps = WORKFLOW["jobs"]["probe"]["steps"]
    return next(s for s in steps if s.get("name", "").startswith(name))


def test_boot_is_ovmf_with_a_fresh_variable_store_and_no_kernel_boot():
    boot = _step("Boot through OVMF")["run"]
    for forbidden in ("-kernel", "-initrd", "-append"):
        assert forbidden not in boot
    assert "OVMF_CODE_4M.fd" in boot and "readonly=on" in boot
    assert "cp /usr/share/OVMF/OVMF_VARS_4M.fd vars.fd" in boot
    assert "-b disk/disk.raw" in boot  # disposable overlay over the prepared disk


def test_workflow_is_read_only_and_tests_itself_on_its_pull_requests():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    on = WORKFLOW[True]
    assert set(on["pull_request"]["paths"]) >= {
        ".github/workflows/first-login-probe.yml", "scripts/first_login_disk.sh",
        "scripts/first_login_probe.py"}
    assert "test_ref" in on["workflow_dispatch"]["inputs"]
    checkout = _step("Checkout")["with"]
    assert checkout["persist-credentials"] is False
    assert "secrets." not in WORKFLOW_TEXT


def test_private_key_stays_on_the_runner():
    upload = _step("Retain evidence")["with"]
    assert upload["path"].strip() == "results/"
    assert 'ssh-keygen -q -t ed25519 -N "" -C "first-login-probe" -f "${RUN_DIR}/key"' in WORKFLOW_TEXT
    assert 'RUN_DIR=${RUNNER_TEMP}/first-login' in _step("Set the per-run directory")["run"]
    assert 'sudo rm -rf "${RUN_DIR}"' in _step("Delete the disk")["run"]


# --- probe logic ------------------------------------------------------------------

def test_wait_for_serial_finds_the_loader_handoff(tmp_path):
    serial = tmp_path / "serial.log"
    serial.write_text("BdsDxe: loading Boot0001 \"UEFI Misc Device\"\nBdsDxe: starting Boot0001\n")
    clock = Clock()
    line = probe.wait_for_serial(serial, probe.LOADER_PATTERNS, 60, clock, clock.sleep)
    assert line.startswith("BdsDxe: loading Boot0001")


def test_wait_for_serial_gives_up_at_the_deadline(tmp_path):
    clock = Clock()
    assert probe.wait_for_serial(tmp_path / "missing.log", (r"never",), 10, clock, clock.sleep) == ""
    assert 10 <= clock.now <= 12


@pytest.mark.parametrize("before,after,expected", [
    (b"P6 a" + b"\x00" * 1000, b"P6 a" + b"\x00" * 1000, False),
    (b"P6 a" + b"\x00" * 1000, b"P6 a" + b"\x01" * 100 + b"\x00" * 900, True),
    (b"P6 a" + b"\x00" * 1000, b"P6 a" + b"\x01" * 10 + b"\x00" * 990, False),  # noise
    (b"", b"P6 a", True),
])
def test_frames_differ(before, after, expected):
    assert probe.frames_differ(before, after) is expected


@pytest.fixture
def fake_vm(monkeypatch):
    state = {"users": [], "gis": True, "frames": [b"A" * 2000, b"A" * 2000, b"B" * 2000]}
    monkeypatch.setattr(probe, "wait_for_serial", lambda serial, patterns, timeout: "Linux version 6" if probe.KERNEL_PATTERN in patterns else "BdsDxe: starting Boot0001")
    monkeypatch.setattr(probe, "wait_for_ssh", lambda key, timeout: True)
    monkeypatch.setattr(probe, "initial_setup_running", lambda key: {
        "running": state["gis"], "processes": "", "sessions": "", "regular_users": state["users"]})
    frames = iter(state["frames"])
    monkeypatch.setattr(probe, "screendump", lambda sock, path: next(frames, b"B" * 2000))
    sent = []
    monkeypatch.setattr(probe, "monitor", lambda sock, command: sent.append(command) or "")
    monkeypatch.setattr(probe.time, "sleep", lambda s: None)
    state["sent"] = sent
    return state


def _verdict(tmp_path):
    return json.loads((tmp_path / "verdict.json").read_text())


def test_probe_passes_all_three_checkpoints(fake_vm, tmp_path):
    assert probe.run(tmp_path, "sock", "serial", "key", 1, 1) == 0
    verdict = _verdict(tmp_path)
    assert verdict["passed"] and verdict["checkpoint"] == 3
    assert any(c.startswith("sendkey") for c in fake_vm["sent"])


def test_probe_fails_when_a_regular_user_already_exists(fake_vm, tmp_path):
    fake_vm["users"] = ["alice 1000"]
    assert probe.run(tmp_path, "sock", "serial", "key", 1, 1) == 1
    assert "already has a regular user" in _verdict(tmp_path)["reason"]


def test_probe_fails_when_initial_setup_never_starts(fake_vm, tmp_path):
    fake_vm["gis"] = False
    assert probe.run(tmp_path, "sock", "serial", "key", 1, 0) == 1
    verdict = _verdict(tmp_path)
    assert verdict["checkpoint"] == 1 and "never started" in verdict["reason"]


def test_probe_fails_when_input_changes_nothing(fake_vm, tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "screendump", lambda sock, path: b"A" * 2000)
    assert probe.run(tmp_path, "sock", "serial", "key", 1, 1) == 1
    verdict = _verdict(tmp_path)
    assert verdict["checkpoint"] == 2 and "did not change" in verdict["reason"]
