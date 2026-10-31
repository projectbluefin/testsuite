"""Unit tests for tests/software/features/steps/compass_flatpark_steps.py.

Parser fixtures are real `flatpak` 1.18 output captured from an
org.tunaos.compass install from FlatPark. These are logic checks, not OS proof.
"""
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


def _import_module():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    qecore_common_stub.__all__ = []
    qecore_stub.common_steps = qecore_common_stub
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    if not hasattr(sys.modules.get("tests.shared"), "__path__"):
        sys.modules.pop("tests.shared", None)
    import tests.shared  # noqa: F401,PLC0415 - real package for submodule imports

    ssh_steps_stub = types.ModuleType("tests.shared.ssh_steps")
    ssh_steps_stub.__all__ = []
    ssh_steps_stub.run_ssh = MagicMock()
    sys.modules["tests.shared.ssh_steps"] = ssh_steps_stub

    for key in list(sys.modules):
        if "software.features.steps" in key:
            del sys.modules[key]

    import tests.software.features.steps.compass_flatpark_steps as m  # noqa: PLC0415
    return m


# patch.dict restores sys.modules afterwards so the stubs cannot leak into
# other test modules collected later in the same run.
with patch.dict(sys.modules):
    m = _import_module()

INFO = """
Compass - A fast, extensible command palette for Linux

            ID: org.tunaos.compass
           Ref: app/org.tunaos.compass/x86_64/stable
          Arch: x86_64
        Branch: stable
        Origin: flatpark
    Collection:
  Installation: system
Installed Size: 51.2 kB
          Date: 2026-10-16 00:35:14 +0000
"""

PERMISSIONS = """[Context]
shared=network;
filesystems=xdg-data/flatpak/app:ro;/var/lib/flatpak/app:ro;host-os:ro;/home/linuxbrew/.linuxbrew/share/applications:ro;

[Session Bus Policy]
org.tunaos.compass.*=own
org.freedesktop.Flatpak=talk
"""


def _ssh(responses):
    """Fake run_ssh: first matching substring → (stdout, rc); records calls."""
    calls = []

    def fake(context, cmd, timeout=60):
        calls.append(cmd)
        for needle, (stdout, rc) in responses.items():
            if needle in cmd:
                context.last_ssh_result = MagicMock(stderr="")
                return stdout, rc
        return "", 0

    return fake, calls


def test_parse_flatpak_info_reads_right_aligned_keys():
    fields = m.parse_flatpak_info(INFO)
    assert (fields["Origin"], fields["Branch"], fields["Arch"]) == ("flatpark", "stable", "x86_64")
    assert fields["Date"] == "2026-10-16 00:35:14 +0000"
    assert "Installed Size" not in fields


def test_remote_filters_splits_on_tab():
    assert m.remote_filters("flathub\t\nflatpark\t/usr/share/flatpak/flatpark.filter\n") == {
        "flathub": "",
        "flatpark": "/usr/share/flatpak/flatpark.filter",
    }


@pytest.mark.parametrize("grants,expected", [
    (["host-os:ro", "xdg-data/applications:ro"], []),
    (["home:ro"], ["home:ro"]),
    (["host"], ["host"]),
    (["~"], ["~"]),
    (["!home"], []),
    (["host-os:ro", "host-root:ro"], ["host-root:ro"]),
])
def test_home_grants(grants, expected):
    assert m.home_grants(grants) == expected


def test_x86_64_gate_skips_other_arches():
    context = MagicMock()
    fake, _ = _ssh({"uname -m": ("aarch64", 0)})
    with patch.object(m, "run_ssh", fake):
        m.vm_is_x86_64_for_compass(context)
    context.scenario.skip.assert_called_once()


def test_x86_64_gate_runs_on_x86_64():
    context = MagicMock()
    fake, _ = _ssh({"uname -m": ("x86_64", 0)})
    with patch.object(m, "run_ssh", fake):
        m.vm_is_x86_64_for_compass(context)
    context.scenario.skip.assert_not_called()


def test_cleanup_is_registered_and_uninstalls_only_when_installed():
    context = MagicMock()
    fake, calls = _ssh({"flatpak info --system": ("", 1)})
    with patch.object(m, "run_ssh", fake):
        m.compass_absent_with_cleanup(context)
    context.add_cleanup.assert_called_once_with(m._remove_compass, context)
    assert not any("flatpak uninstall" in c for c in calls)

    fake, calls = _ssh({"flatpak info --system": ("", 0)})
    with patch.object(m, "run_ssh", fake):
        m._remove_compass(context)
    assert "sudo -n flatpak uninstall -y --system org.tunaos.compass" in calls


def test_failed_uninstall_in_cleanup_raises():
    fake, _ = _ssh({"flatpak info --system": ("", 0), "uninstall": ("", 1)})
    with patch.object(m, "run_ssh", fake), pytest.raises(AssertionError):
        m._remove_compass(MagicMock())


def test_ref_step_rejects_wrong_origin():
    fake, _ = _ssh({"flatpak info --system": (INFO.replace("flatpark", "flathub"), 0)})
    with patch.object(m, "run_ssh", fake), pytest.raises(AssertionError):
        m.flatpak_system_app_reports_ref(MagicMock(), m.COMPASS_APP_ID, "flatpark", "stable", "x86_64")


def test_remote_filter_step_rejects_missing_filter():
    fake, _ = _ssh({"flatpak remotes": ("flatpark\t", 0)})
    with patch.object(m, "run_ssh", fake), pytest.raises(AssertionError):
        m.flatpak_system_remote_uses_filter(MagicMock(), "flatpark", "/usr/share/flatpak/flatpark.filter")


def test_permission_contract_on_real_output():
    context = MagicMock()
    fake, _ = _ssh({"--show-permissions": (PERMISSIONS, 0)})
    with patch.object(m, "run_ssh", fake):
        m.flatpak_system_app_permission_sets(
            context, m.COMPASS_APP_ID, "Session Bus Policy", "org.freedesktop.Flatpak", "talk"
        )
        m.flatpak_system_app_filesystems_include(context, m.COMPASS_APP_ID, "host-os:ro")
        m.flatpak_system_app_has_no_home_grant(context, m.COMPASS_APP_ID)


def test_home_grant_fails_the_contract():
    fake, _ = _ssh({"--show-permissions": (PERMISSIONS.replace("host-os:ro;", "host-os:ro;home:ro;"), 0)})
    with patch.object(m, "run_ssh", fake), pytest.raises(AssertionError):
        m.flatpak_system_app_has_no_home_grant(MagicMock(), m.COMPASS_APP_ID)


def test_engine_runs_as_a_user_unit_outside_the_ssh_session():
    """Run 41219770747: Dakota's logind KillUserProcesses=yes killed an SSH-started engine."""
    import shlex

    assert m._COMPASS_LAUNCH.startswith(m._IN_SESSION)
    argv = shlex.split(m._COMPASS_LAUNCH.removeprefix(m._IN_SESSION))
    assert argv[:4] == ["systemd-run", "--user", "--collect", "--expand-environment=no"]
    assert f"--unit={m.COMPASS_UNIT}" in argv
    assert f"StandardOutput=truncate:{m.COMPASS_SERVE_LOG}" in argv and "StandardError=inherit" in argv
    assert argv[-3:] == ["sh", "-c", f"{m._COMPASS_RUN} serve --no-hotkey"]


def test_ping_timeout_reports_stderr_log_unit_and_logind_state():
    context = MagicMock()
    calls = []

    def fake(ctx, cmd, timeout=60):
        calls.append(cmd)
        ctx.last_ssh_result = MagicMock(stderr="no Compass engine is listening")
        if cmd.endswith(" ping"):
            return "", 1
        if "== systemctl --user show" in cmd:
            return "ActiveState=failed\n== /tmp/compass-serve.log\nboom", 0
        return "", 0

    with patch.object(m, "run_ssh", fake), patch.object(m, "time") as clock:
        clock.monotonic.side_effect = [0, 100]
        with pytest.raises(AssertionError) as raised:
            m.compass_engine_runs_in_session(context)
    message = str(raised.value)
    assert "stderr: no Compass engine is listening" in message
    assert "ActiveState=failed" in message and "boom" in message
    diagnostics = next(c for c in calls if "== systemctl --user show" in c)
    assert diagnostics.startswith("{ ") and diagnostics.endswith("; } 2>&1")
    for probe in (f"cat {m.COMPASS_SERVE_LOG}", "flatpak ps", "KillUserProcesses"):
        assert probe in diagnostics


def test_cleanup_stops_the_unit_and_kills_a_leftover_instance():
    fake, calls = _ssh({"flatpak ps": ("", 0)})
    with patch.object(m, "run_ssh", fake):
        m._stop_compass(MagicMock())
    assert f"{m._IN_SESSION}systemctl --user stop {m.COMPASS_UNIT}" in calls
    assert "flatpak kill org.tunaos.compass" in calls


PING = "engine alive on /run/user/1000/app/org.tunaos.compass/testsuite-ipc.sock: protocol v3, pid 2"


def test_engine_step_pings_then_shuts_down_and_waits_for_exit():
    context = MagicMock()
    ps = iter([0, 1])
    calls = []

    def fake(ctx, cmd, timeout=60):
        calls.append(cmd)
        ctx.last_ssh_result = MagicMock(stderr="")
        if cmd.endswith(" ping"):
            return PING, 0
        if "flatpak ps" in cmd:
            return "", next(ps)
        return "", 0

    with patch.object(m, "run_ssh", fake):
        m.compass_engine_runs_in_session(context)
    context.add_cleanup.assert_called_once_with(m._stop_compass, context)
    assert calls[0] == m._COMPASS_LAUNCH
    assert [c for c in calls if c.endswith(" shutdown")] == [f"{m._COMPASS_RUN} shutdown"]


def test_engine_step_rejects_a_ping_from_another_socket():
    fake, _ = _ssh({" ping": (PING.replace("testsuite-ipc.sock", "ipc.sock"), 0)})
    with patch.object(m, "run_ssh", fake), pytest.raises(AssertionError):
        m.compass_engine_runs_in_session(MagicMock())
