"""Unit tests for tests/smoke/features/steps/printing_steps.py.

Tests focus on pure helpers that do not need a live CUPS scheduler:
- _parse_job_id(): lp stdout parsing
- _unmask_cups(): unmasks only masked CUPS units
"""
import sys
import types
from unittest.mock import patch


def _import_steps():
    """Import printing_steps.py with all GNOME dependencies stubbed out."""
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    # printing_steps imports _run_host from system_health_steps; provide a stub.
    system_health_stub = types.ModuleType("system_health_steps")
    system_health_stub._run_host = lambda cmd, timeout=30: ("", 0, "")
    sys.modules["system_health_steps"] = system_health_stub

    for key in list(sys.modules):
        if "printing_steps" in key:
            del sys.modules[key]

    import tests.smoke.features.steps.printing_steps as m  # noqa: PLC0415
    return m


class TestParseJobId:
    def test_standard_request_id_format(self):
        m = _import_steps()
        assert m._parse_job_id("request id is smokeprint-1 (1 file(s))") == "smokeprint-1"

    def test_name_hyphen_number_fallback(self):
        m = _import_steps()
        assert m._parse_job_id("queued job printer-42") == "printer-42"

    def test_returns_none_when_no_id_present(self):
        m = _import_steps()
        assert m._parse_job_id("scheduler is running") is None

    def test_empty_string_returns_none(self):
        m = _import_steps()
        assert m._parse_job_id("") is None


class TestUnmaskCups:
    def test_unmasks_all_units_and_reloads_daemon(self):
        m = _import_steps()
        calls = []

        def fake_run_host(cmd, timeout=30):
            calls.append(cmd)
            return ("", 0, "")

        with patch.object(m, "_run_host", side_effect=fake_run_host):
            m._unmask_cups()

        unmask_commands = [c for c in calls if c.startswith("sudo -n systemctl unmask")]
        assert len(unmask_commands) == 4
        assert any("cups.socket" in c for c in unmask_commands)
        assert any("cups.service" in c for c in unmask_commands)
        assert any("cp /usr/lib/systemd/system/cups.socket /etc/systemd/system.control/cups.socket" in c for c in calls)
        assert "sudo -n mkdir -p /etc/systemd/system.control" in calls
        assert "sudo -n systemctl daemon-reload" in calls


class TestSocketListener:
    def test_listener_outlives_the_ssh_session(self):
        m = _import_steps()
        calls = []

        def fake_run_host(cmd, timeout=30):
            calls.append(cmd)
            if cmd.startswith("test -f"):
                return ("ready", 0, "")
            return ("", 0, "")

        with patch.object(m, "_run_host", side_effect=fake_run_host):
            m._start_socket_listener(19191)

        launch = [c for c in calls if f"python3 {m._LISTENER_SCRIPT}" in c]
        assert len(launch) == 1
        assert "systemd-run --user" in launch[0]
