"""Unit coverage for the capture path of tests/shared/screenshot.py.

tests/unit/test_screenshot.py covers the pure helpers (``_safe_fragment``,
``_screenshot_path``, ``_flatpak_installed``). This module covers the capture
path itself, which every GNOME GUI suite depends on for failure artifacts:

* ``_ssh_run``          — SSH argv construction from the VM env vars
* ``_take_screenshot_via_ssh`` — grim → gnome-screenshot → gdbus fallback chain
* ``_gdbus_screenshot`` — container (SSH) vs on-VM (local gdbus) routing
* ``take_screenshot``   — stale-file removal and the materialization wait loop
* ``take_app_screenshot`` — launcher selection and process teardown
* ``take_fastfetch_screenshot`` — terminal selection and no-terminal fallback
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.shared import screenshot


def _completed(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# ── _ssh_run ─────────────────────────────────────────────────────────────────


def test_ssh_run_builds_argv_from_vm_environment(monkeypatch):
    monkeypatch.setenv("SSH_KEY", "/keys/id_test")
    monkeypatch.setenv("VM_IP", "10.0.0.5")
    monkeypatch.setenv("VM_USER", "tester")
    monkeypatch.setenv("SSH_PORT", "2222")

    with patch("tests.shared.screenshot.subprocess.run", return_value=_completed()) as run_mock:
        screenshot._ssh_run("echo hi", timeout=7)

    argv = run_mock.call_args.args[0]
    assert argv[0] == "ssh"
    assert argv[-1] == "echo hi"
    assert argv[-2] == "tester@10.0.0.5"
    assert "/keys/id_test" in argv
    assert "2222" in argv
    assert "StrictHostKeyChecking=no" in argv
    assert run_mock.call_args.kwargs["timeout"] == 7
    assert run_mock.call_args.kwargs["capture_output"] is True


def test_ssh_run_falls_back_to_default_vm_identity(monkeypatch):
    for var in ("SSH_KEY", "VM_IP", "VM_USER", "SSH_PORT"):
        monkeypatch.delenv(var, raising=False)

    with patch("tests.shared.screenshot.subprocess.run", return_value=_completed()) as run_mock:
        screenshot._ssh_run("true")

    argv = run_mock.call_args.args[0]
    assert "bluefin-test@127.0.0.1" in argv
    assert "/home/bluefin-test/.ssh/id_ed25519" in argv
    assert "22" in argv


# ── _take_screenshot_via_ssh fallback chain ──────────────────────────────────


def test_via_ssh_returns_on_first_grim_success(monkeypatch):
    calls = []

    def fake_ssh(cmd, timeout=15):
        calls.append(cmd)
        return _completed(0)

    monkeypatch.setattr(screenshot, "_ssh_run", fake_ssh)

    assert screenshot._take_screenshot_via_ssh("/tmp/out.png") is True
    assert len(calls) == 1
    assert "grim" in calls[0]
    # The remote command sources the session env so Wayland vars are present.
    assert calls[0].startswith("source /tmp/session.env && ")


def test_via_ssh_falls_back_to_gnome_screenshot_when_grim_missing(monkeypatch):
    calls = []

    def fake_ssh(cmd, timeout=15):
        calls.append(cmd)
        if "grim" in cmd:
            return _completed(127, stderr="bash: grim: command not found")
        return _completed(0)

    monkeypatch.setattr(screenshot, "_ssh_run", fake_ssh)

    assert screenshot._take_screenshot_via_ssh("/tmp/out.png") is True
    assert len(calls) == 2
    assert "gnome-screenshot -f" in calls[1]


def test_via_ssh_quotes_paths_with_spaces(monkeypatch):
    calls = []

    def fake_ssh(cmd, timeout=15):
        calls.append(cmd)
        return _completed(0)

    monkeypatch.setattr(screenshot, "_ssh_run", fake_ssh)

    screenshot._take_screenshot_via_ssh("/tmp/a b/out.png")

    assert "'/tmp/a b/out.png'" in calls[0]


def test_via_ssh_falls_through_to_gdbus_and_enables_unsafe_mode(monkeypatch):
    calls = []

    def fake_ssh(cmd, timeout=15):
        calls.append(cmd)
        if "grim" in cmd or "gnome-screenshot" in cmd:
            return _completed(1, stderr="boom")
        return _completed(0)

    monkeypatch.setattr(screenshot, "_ssh_run", fake_ssh)

    assert screenshot._take_screenshot_via_ssh("/tmp/out.png") is True

    unsafe_calls = [c for c in calls if "SetUnsafeMode" in c or "unsafe_mode = true" in c]
    # SetUnsafeMode succeeded, so Shell.Eval must not be attempted.
    assert len(unsafe_calls) == 1
    assert "SetUnsafeMode" in unsafe_calls[0]
    assert any("org.gnome.Shell.Screenshot.Screenshot" in c for c in calls)


def test_via_ssh_tries_shell_eval_when_set_unsafe_mode_fails(monkeypatch):
    calls = []

    def fake_ssh(cmd, timeout=15):
        calls.append(cmd)
        if "SetUnsafeMode" in cmd:
            return _completed(1, stderr="rejected")
        if "grim" in cmd or "gnome-screenshot" in cmd:
            return _completed(1, stderr="boom")
        return _completed(0)

    monkeypatch.setattr(screenshot, "_ssh_run", fake_ssh)

    assert screenshot._take_screenshot_via_ssh("/tmp/out.png") is True
    assert any("unsafe_mode = true" in c for c in calls)


def test_via_ssh_returns_false_when_every_method_fails(monkeypatch):
    monkeypatch.setattr(
        screenshot, "_ssh_run", lambda cmd, timeout=15: _completed(1, stderr="nope")
    )

    assert screenshot._take_screenshot_via_ssh("/tmp/out.png") is False


def test_via_ssh_passes_gdbus_path_as_quoted_gvariant(monkeypatch):
    calls = []

    def fake_ssh(cmd, timeout=15):
        calls.append(cmd)
        if "Screenshot.Screenshot" in cmd:
            return _completed(0)
        return _completed(1, stderr="boom")

    monkeypatch.setattr(screenshot, "_ssh_run", fake_ssh)

    screenshot._take_screenshot_via_ssh("/tmp/out.png")

    gdbus = next(c for c in calls if "Screenshot.Screenshot" in c)
    assert 'true false \'"/tmp/out.png"\'' in gdbus


# ── _gdbus_screenshot routing ────────────────────────────────────────────────


def test_gdbus_screenshot_routes_over_ssh_inside_container(monkeypatch):
    monkeypatch.setattr(screenshot, "_IN_CONTAINER", True)
    with patch("tests.shared.screenshot._take_screenshot_via_ssh", return_value=True) as via_ssh:
        with patch("tests.shared.screenshot.subprocess.run") as run_mock:
            assert screenshot._gdbus_screenshot("/tmp/out.png") is True

    via_ssh.assert_called_once_with("/tmp/out.png")
    run_mock.assert_not_called()


@pytest.mark.parametrize(("returncode", "expected"), [(0, True), (1, False)])
def test_gdbus_screenshot_runs_local_gdbus_on_vm(monkeypatch, returncode, expected):
    monkeypatch.setattr(screenshot, "_IN_CONTAINER", False)

    with patch(
        "tests.shared.screenshot.subprocess.run",
        return_value=_completed(returncode, stderr="err"),
    ) as run_mock:
        assert screenshot._gdbus_screenshot("/tmp/out.png") is expected

    argv = run_mock.call_args.args[0]
    assert argv[0] == "gdbus"
    # The path is passed as a JSON-encoded GVariant string, not bare.
    assert argv[-1] == '"/tmp/out.png"'
    assert "org.gnome.Shell.Screenshot.Screenshot" in argv


# ── take_screenshot ──────────────────────────────────────────────────────────


def test_take_screenshot_returns_path_once_file_materializes(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTSUITE_RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(screenshot, "_CURRENT_CONTEXT", None)
    monkeypatch.setattr(screenshot, "_CURRENT_SUITE", "smoke")
    monkeypatch.setattr(screenshot, "_CURRENT_SCENARIO", "scenario")

    def fake_capture(path):
        open(path, "wb").close()
        return True

    monkeypatch.setattr(screenshot, "_gdbus_screenshot", fake_capture)

    result = screenshot.take_screenshot("label")

    assert result is not None
    assert result.endswith(".png")
    assert "label" in result


def test_take_screenshot_deletes_stale_file_before_capturing(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTSUITE_RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(screenshot, "_CURRENT_CONTEXT", None)
    monkeypatch.setattr(screenshot, "_CURRENT_SUITE", "smoke")
    monkeypatch.setattr(screenshot, "_CURRENT_SCENARIO", "scenario")
    monkeypatch.setattr(screenshot, "_CAPTURE_WAIT_SECONDS", 0.0)

    stale = screenshot._screenshot_path("label")
    with open(stale, "w", encoding="utf-8") as handle:
        handle.write("stale")

    seen = {}

    def fake_capture(path):
        seen["existed"] = screenshot.os.path.exists(path)
        return True

    monkeypatch.setattr(screenshot, "_gdbus_screenshot", fake_capture)

    # A stale file must never be reported as a fresh capture.
    assert screenshot.take_screenshot("label") is None
    assert seen["existed"] is False


def test_take_screenshot_returns_none_when_capture_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTSUITE_RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(screenshot, "_CURRENT_CONTEXT", None)
    monkeypatch.setattr(screenshot, "_gdbus_screenshot", lambda path: False)

    assert screenshot.take_screenshot("label") is None


def test_take_screenshot_creates_results_dir(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "results"
    monkeypatch.setenv("TESTSUITE_RESULTS_DIR", str(target))
    monkeypatch.setattr(screenshot, "_CURRENT_CONTEXT", None)
    monkeypatch.setattr(screenshot, "_gdbus_screenshot", lambda path: False)

    screenshot.take_screenshot("label")

    assert target.is_dir()


# ── take_app_screenshot ──────────────────────────────────────────────────────


class _FakeProc:
    def __init__(self):
        self.terminated = False
        self.waited = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True


@pytest.fixture
def _app_launch(monkeypatch):
    proc = _FakeProc()
    launched = {}

    def fake_popen(cmd, **kwargs):
        launched["cmd"] = cmd
        return proc

    monkeypatch.setattr(screenshot.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(screenshot.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(screenshot, "take_screenshot", lambda label, context=None: f"/r/{label}.png")
    return SimpleNamespace(proc=proc, launched=launched)


def test_take_app_screenshot_prefers_flatpak_for_installed_app_id(monkeypatch, _app_launch):
    monkeypatch.setattr(screenshot, "_flatpak_installed", lambda app_id: True)

    assert screenshot.take_app_screenshot("org.gnome.Calculator", wait=0) == "/r/org.gnome.Calculator.png"
    assert _app_launch.launched["cmd"] == ["flatpak", "run", "org.gnome.Calculator"]
    assert _app_launch.proc.terminated is True


def test_take_app_screenshot_uses_binary_on_path_when_not_a_flatpak(monkeypatch, _app_launch):
    monkeypatch.setattr(screenshot, "_flatpak_installed", lambda app_id: False)
    monkeypatch.setattr(screenshot.shutil, "which", lambda name: "/usr/bin/nautilus")

    screenshot.take_app_screenshot("nautilus", label="files", wait=0)

    assert _app_launch.launched["cmd"] == ["nautilus"]


def test_take_app_screenshot_falls_back_to_gtk_launch_without_desktop_suffix(monkeypatch, _app_launch):
    monkeypatch.setattr(screenshot, "_flatpak_installed", lambda app_id: False)
    monkeypatch.setattr(screenshot.shutil, "which", lambda name: None)

    screenshot.take_app_screenshot("org.gnome.Nautilus.desktop", wait=0)

    assert _app_launch.launched["cmd"] == ["gtk-launch", "org.gnome.Nautilus"]


def test_take_app_screenshot_returns_none_when_launch_raises(monkeypatch):
    monkeypatch.setattr(screenshot, "_flatpak_installed", lambda app_id: False)
    monkeypatch.setattr(screenshot.shutil, "which", lambda name: None)

    def boom(cmd, **kwargs):
        raise OSError("no such binary")

    monkeypatch.setattr(screenshot.subprocess, "Popen", boom)

    assert screenshot.take_app_screenshot("missing-app", wait=0) is None


def test_take_app_screenshot_still_returns_when_terminate_raises(monkeypatch, _app_launch):
    monkeypatch.setattr(screenshot, "_flatpak_installed", lambda app_id: False)
    monkeypatch.setattr(screenshot.shutil, "which", lambda name: "/usr/bin/app")

    def boom():
        raise OSError("already gone")

    monkeypatch.setattr(_app_launch.proc, "terminate", boom)

    assert screenshot.take_app_screenshot("app", wait=0) == "/r/app.png"


# ── take_fastfetch_screenshot ────────────────────────────────────────────────


def test_fastfetch_uses_first_available_terminal(monkeypatch):
    proc = _FakeProc()
    launched = {}

    monkeypatch.setattr(screenshot.shutil, "which", lambda name: "/usr/bin/kgx" if name == "kgx" else None)
    monkeypatch.setattr(screenshot.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        screenshot.subprocess, "Popen", lambda cmd, **kwargs: (launched.setdefault("cmd", cmd), proc)[1]
    )
    monkeypatch.setattr(screenshot, "take_screenshot", lambda label, context=None: "/r/fastfetch.png")

    assert screenshot.take_fastfetch_screenshot() == "/r/fastfetch.png"
    assert launched["cmd"][0] == "kgx"
    assert proc.terminated is True


def test_fastfetch_falls_back_to_plain_desktop_screenshot_without_terminal(monkeypatch):
    monkeypatch.setattr(screenshot.shutil, "which", lambda name: None)
    labels = []
    monkeypatch.setattr(
        screenshot,
        "take_screenshot",
        lambda label, context=None: labels.append(label) or "/r/fastfetch.png",
    )
    monkeypatch.setattr(screenshot.subprocess, "Popen", lambda *a, **k: pytest.fail("no terminal to launch"))

    assert screenshot.take_fastfetch_screenshot() == "/r/fastfetch.png"
    assert labels == ["fastfetch"]


def test_fastfetch_returns_none_when_every_terminal_attempt_fails(monkeypatch):
    proc = _FakeProc()
    monkeypatch.setattr(screenshot.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(screenshot.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(screenshot.subprocess, "Popen", lambda cmd, **kwargs: proc)
    monkeypatch.setattr(screenshot, "take_screenshot", lambda label, context=None: None)

    # A terminal existed, so the no-terminal desktop fallback must not run.
    assert screenshot.take_fastfetch_screenshot() is None


def test_fastfetch_recovers_from_terminal_launch_exception(monkeypatch):
    monkeypatch.setattr(screenshot.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(screenshot.time, "sleep", lambda seconds: None)

    attempts = []

    def flaky_popen(cmd, **kwargs):
        attempts.append(cmd[0])
        if len(attempts) == 1:
            raise OSError("ptyxis crashed")
        return _FakeProc()

    monkeypatch.setattr(screenshot.subprocess, "Popen", flaky_popen)
    monkeypatch.setattr(screenshot, "take_screenshot", lambda label, context=None: "/r/fastfetch.png")

    assert screenshot.take_fastfetch_screenshot() == "/r/fastfetch.png"
    assert attempts == ["ptyxis", "kgx"]
