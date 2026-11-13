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
    steps = WORKFLOW["jobs"]["journey"]["steps"]
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


def _ppm(rows, width=4):
    """A P6 frame whose row y is filled with the byte rows[y]."""
    return (b"P6\n# probe\n%d %d\n255\n" % (width, len(rows))
            + b"".join(bytes([v]) * width * 3 for v in rows))


def test_changed_rows_reads_ppm_headers_with_comments():
    assert probe.changed_rows(_ppm([0, 0, 0, 0]), _ppm([0, 9, 0, 9])) == {1, 3}


def test_rows_that_animate_while_idle_do_not_count_as_input():
    # Run 43333610574: the greeting row changed with no input at all.
    idle = [_ppm([0, g, 0, 0, 0, 0, 0, 0]) for g in (1, 2, 3)]
    rows, animated = probe.input_changed_rows(idle, _ppm([0, 4, 0, 0, 0, 0, 0, 0]))
    assert rows == set() and animated == {1}
    rows, _ = probe.input_changed_rows(idle, _ppm([0, 4, 0, 7, 7, 7, 7, 0]))
    assert rows == {3, 4, 5, 6}


@pytest.fixture
def fake_vm(monkeypatch):
    still, moved = _ppm([250] * 8), _ppm([250, 250, 205, 205, 205, 205, 250, 250])
    # Checkpoint 1 takes one frame and settling two; the settled frame is the
    # first idle frame.
    state = {"users": [], "gis": True,
             "frames": [still] * (2 + probe.IDLE_FRAMES) + [moved]}
    monkeypatch.setattr(probe, "wait_for_serial", lambda serial, patterns, timeout: "Linux version 6" if probe.KERNEL_PATTERN in patterns else "BdsDxe: starting Boot0001")
    monkeypatch.setattr(probe, "wait_for_ssh", lambda key, timeout: True)
    monkeypatch.setattr(probe, "initial_setup_running", lambda key: {
        "running": state["gis"], "processes": "", "sessions": "", "regular_users": state["users"]})
    frames = iter(state["frames"])
    monkeypatch.setattr(probe, "screendump", lambda sock, path: next(frames, moved))
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
    monkeypatch.setattr(probe, "screendump", lambda sock, path: _ppm([250] * 8))
    assert probe.run(tmp_path, "sock", "serial", "key", 1, 1) == 1
    verdict = _verdict(tmp_path)
    assert verdict["checkpoint"] == 2 and "did not change" in verdict["reason"]


def test_wait_for_serial_tolerates_an_unreadable_log(tmp_path):
    serial = tmp_path / "serial.log"
    serial.write_text("Linux version 6.17\n")
    serial.chmod(0)
    clock = Clock()
    try:
        assert probe.wait_for_serial(serial, (r"never",), 4, clock, clock.sleep) == ""
    finally:
        serial.chmod(0o644)


def test_serial_log_is_created_as_the_runner_user_before_boot():
    boot = _step("Boot through OVMF")["run"]
    assert boot.index(': > "${RUN_DIR}/serial.log"') < boot.index("qemu-system-x86_64")


def test_disk_enables_sshd_with_labelled_host_keys():
    # Bluefin images ship sshd disabled; without this the probe can't reach the guest.
    assert "multi-user.target.wants/sshd.service" in DISK_SCRIPT
    assert 'ssh-keygen -A -f "$DEP"' in DISK_SCRIPT
    assert "-name 'ssh_host_*' | tee -a \"$LABEL_LIST\"" in DISK_SCRIPT


def test_probe_reports_a_missing_frame_separately(fake_vm, tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "screendump", lambda sock, path: b"")
    assert probe.run(tmp_path, "sock", "serial", "key", 1, 1) == 1
    assert _verdict(tmp_path)["reason"] == "QEMU screendump produced no frame"


def test_screendump_sends_qemu_an_absolute_path(tmp_path, monkeypatch):
    # The daemonized QEMU runs from /, so a relative path would land there.
    monkeypatch.chdir(tmp_path)
    sent = []

    def monitor(sock, command):
        sent.append(command)
        Path(command.split(" ", 1)[1]).write_bytes(b"P6 frame")
        return ""

    monkeypatch.setattr(probe, "monitor", monitor)
    assert probe.screendump("sock", "frame.ppm") == b"P6 frame"
    assert sent == [f"screendump {tmp_path / 'frame.ppm'}"]


def test_screendump_creates_the_frame_file_before_qemu_writes_it(tmp_path, monkeypatch):
    # QEMU runs as root; a file it creates itself was unreadable to the probe.
    seen = {}

    def monitor(sock, command):
        seen["existed"] = Path(command.split(" ", 1)[1]).exists()
        return "could not open"

    monkeypatch.setattr(probe, "monitor", monitor)
    monkeypatch.setattr(probe.time, "sleep", lambda s: None)
    assert probe.screendump("sock", tmp_path / "frame.ppm") == b""
    assert seen["existed"]


def test_probe_fails_when_only_the_animated_greeting_changes(fake_vm, tmp_path, monkeypatch):
    frames = iter([_ppm([250, 200 + g, 250, 250, 250, 250, 250, 250])
                   for g in range(probe.IDLE_FRAMES + 3)])
    monkeypatch.setattr(probe, "screendump", lambda sock, path: next(frames))
    assert probe.run(tmp_path, "sock", "serial", "key", 1, 1) == 1
    verdict = _verdict(tmp_path)
    assert verdict["frames"] == {"bytes": len(_ppm([0] * 8)), "animated_rows": 1, "input_rows": 0}

    assert "animate on their own" in verdict["reason"]


def test_settled_frame_waits_for_the_window_to_finish_appearing(monkeypatch):
    # Run 43335035900: two identical frames of bare wallpaper (dark) came
    # before the window mapped, then the whole screen changed.
    monkeypatch.setattr(probe, "SETTLED_ROWS", 3)
    frames = iter([_ppm([0] * 8), _ppm([0] * 8), _ppm([250] * 8),
                   _ppm([250] * 7 + [201]), _ppm([250] * 7 + [202])])
    monkeypatch.setattr(probe, "screendump", lambda sock, path: next(frames))
    clock = Clock()
    monkeypatch.setattr(probe.time, "monotonic", clock)
    monkeypatch.setattr(probe.time, "sleep", clock.sleep)
    assert probe.settled_frame("sock", "frame.ppm") == (_ppm([250] * 7 + [201]), True)


def test_probe_fails_when_the_page_never_settles(fake_vm, tmp_path, monkeypatch):
    frames = iter([_ppm([200 + g % 50] * 8) for g in range(200)])
    monkeypatch.setattr(probe, "screendump", lambda sock, path: next(frames))
    clock = Clock()
    monkeypatch.setattr(probe.time, "monotonic", clock)
    monkeypatch.setattr(probe.time, "sleep", clock.sleep)
    monkeypatch.setattr(probe, "SETTLED_ROWS", 3)
    assert probe.run(tmp_path, "sock", "serial", "key", 1, 1) == 1
    assert _verdict(tmp_path)["reason"] == "the Initial Setup page never appeared or never stopped changing"


def test_page_visible_tells_the_card_from_dark_wallpaper():
    assert probe.page_visible(_ppm([250] * 16, width=16))
    assert not probe.page_visible(_ppm([40] * 16, width=16))
