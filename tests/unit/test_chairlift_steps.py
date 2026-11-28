"""Unit tests for tests/chairlift/features/steps/steps.py.

The SSH hop and the AT-SPI tree are replaced by fakes, so these check command
construction, parsing, polling and assertion branches. They are logic checks,
not proof of what a booted image or polkit does.
"""
import json
import os
import shlex
import subprocess
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _import_module():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub
    for key in list(sys.modules):
        if "chairlift.features.steps" in key:
            del sys.modules[key]
    import tests.chairlift.features.steps.steps as m  # noqa: PLC0415
    return m


# patch.dict restores sys.modules afterwards so the stub cannot leak into
# other test modules collected later in the same run.
with patch.dict(sys.modules):
    m = _import_module()


class Node:
    """A stand-in for a dogtail node: role, name, states, actions, children."""

    def __init__(self, role, name="", children=(), showing=True, actions=(), checked=False, sensitive=True):
        self.roleName = role
        self.name = name
        self.children = list(children)
        self.showing = showing
        self.actions = {action: object() for action in actions}
        self.checked = checked
        self.sensitive = sensitive
        self.parent = None
        self.done = []
        for child in self.children:
            child.parent = self

    def findChildren(self, predicate):
        found = []
        for child in self.children:
            if predicate(child):
                found.append(child)
            found.extend(child.findChildren(predicate))
        return found

    def do_action_named(self, action):
        self.done.append(action)

    def getState(self):
        raise RuntimeError("no state set in the fake")


def _app(switch=None, title="Control Center", app_name="chairlift", sidebar=True):
    switch = switch or Node("switch", actions=("toggle",), checked=True)
    row = Node("list item", "Automatic Updates", [Node("label", "Automatic Updates"), switch])
    pages = [Node("list item", "", [Node("label", page)]) for page in ("Updates", "Apps", "Help")]
    content = [Node("list box", "", [row])]
    if sidebar:
        content.insert(0, Node("list", "Navigation", pages))
    window = Node("frame", title, content)
    return Node("application", app_name, [window]), window, switch


def _tree(*apps):
    return SimpleNamespace(root=SimpleNamespace(applications=lambda: list(apps)))


def _ssh(responses):
    """Fake run_ssh: first matching substring wins; a list answers call by call."""
    calls = []

    def fake(context, cmd, timeout=60):
        calls.append(cmd)
        for needle, answer in responses.items():
            if needle in cmd:
                if isinstance(answer, list):
                    answer = answer.pop(0) if len(answer) > 1 else answer[0]
                return answer
        return "", 0

    return fake, calls


def _context(tmp_path=None):
    userdata = {"results_dir": str(tmp_path)} if tmp_path else {}
    return SimpleNamespace(config=SimpleNamespace(userdata=userdata), scenario=MagicMock())


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(m, "sleep", lambda _seconds: None)
    monkeypatch.setattr(m, "tree", None)


INSTALLED = "\n".join([
    "uptime_s=900", "launcher=yes", "installed_s=312", "brew=yes", "setup_marker=yes", "cask=26.11.9 ",
    "setup.LoadState=loaded", "setup.ActiveState=inactive", "setup.SubState=dead", "setup.Result=success",
    "setup.UnitFileState=enabled", "setup.InactiveExitTimestampMonotonic=9000000", "setup.InactiveEnterTimestampMonotonic=41000000",
    "preinstall.LoadState=loaded", "preinstall.ActiveState=activating", "preinstall.SubState=start",
    "preinstall.Result=success", "preinstall.ConditionResult=yes", "preinstall.UnitFileState=enabled", "preinstall.NRestarts=0",
    "preinstall.InactiveExitTimestampMonotonic=62000000", "preinstall.ActiveEnterTimestampMonotonic=0",
])
SKIPPED = "\n".join([
    "uptime_s=900", "launcher=no", "brew=yes", "setup_marker=yes", "cask=",
    "setup.LoadState=loaded", "setup.ActiveState=inactive", "setup.SubState=dead", "setup.Result=success",
    "preinstall.LoadState=loaded", "preinstall.ActiveState=inactive", "preinstall.SubState=dead",
    "preinstall.Result=success", "preinstall.Job=", "preinstall.ConditionResult=no", "preinstall.UnitFileState=enabled", "preinstall.NRestarts=0",
])


def test_key_values_ignores_lines_without_a_key():
    assert m._key_values("a=1\n=x\nnoise\n b = two=2 \n") == {"a": "1", "b": "two=2"}


@pytest.mark.parametrize("change,expected", [
    ({}, True),
    ({"launcher": "yes"}, False),
    ({"brew": "no"}, False),
    ({"setup_marker": "no"}, False),
    ({"setup.ActiveState": "activating"}, False),
    ({"preinstall.ActiveState": "activating"}, False),
    ({"preinstall.ActiveState": "active"}, False),
    ({"preinstall.ActiveState": "failed"}, True),
    ({"preinstall.Job": "42"}, False),
    ({"preinstall.LoadState": "not-found"}, False),
])
def test_needs_manual_start(change, expected):
    state = {**m._key_values(SKIPPED), **change}
    assert m.needs_manual_start(state) is expected


def test_install_report_reads_boot_relative_times():
    report = m.install_report(m._key_values(INSTALLED), 3.4, "")
    assert "launcher linked at boot+312s (5.2 min after boot)" in report
    assert "cask version(s): 26.11.9" in report
    assert "brew-setup ran boot+9s to boot+41s" in report
    assert "brew-preinstall last started boot+62s, finished never (now activating/start, restarts 0)" in report
    assert report.endswith("manual start needed: no")
    assert "? min" in m.install_report({}, 0, "x") and "manual start needed: YES, from x" in m.install_report({}, 0, "x")


def test_homebrew_step_passes_and_prints_the_answer_when_already_installed(monkeypatch, capsys):
    fake, calls = _ssh({"uptime_s": (INSTALLED, 0)})
    monkeypatch.setattr(m, "run_ssh", fake)
    m.homebrew_setup_installs_control_center(_context())
    out = capsys.readouterr().out
    assert "CHAIRLIFT install: launcher linked at boot+312s" in out
    assert "launcher=yes brew=yes brew-setup=loaded/inactive/dead/success (enabled)" in out
    assert calls == [m.BREW_PROBE]


def test_homebrew_step_starts_a_skipped_unit_once_and_then_fails(monkeypatch, capsys):
    running = SKIPPED.replace("preinstall.ActiveState=inactive", "preinstall.ActiveState=activating")
    fake, calls = _ssh({
        "uptime_s": [(SKIPPED, 0), (running, 0), (INSTALLED, 0)],
        "reset-failed": ("", 0),
        "who owns": ("DIAGNOSTICS", 0),
    })
    monkeypatch.setattr(m, "run_ssh", fake)
    with pytest.raises(AssertionError, match="had to be started by hand") as raised:
        m.homebrew_setup_installs_control_center(_context())
    assert calls.count(m.MANUAL_START) == 1
    assert "condition=no" in str(raised.value) and "DIAGNOSTICS" in str(raised.value)
    assert "manual start needed: YES" in capsys.readouterr().out


def test_homebrew_step_gives_up_when_the_manual_start_does_not_help(monkeypatch):
    failed = SKIPPED.replace("preinstall.ActiveState=inactive", "preinstall.ActiveState=failed")
    fake, calls = _ssh({"uptime_s": (failed, 0), "who owns": ("DIAGNOSTICS", 0)})
    monkeypatch.setattr(m, "run_ssh", fake)
    with pytest.raises(AssertionError, match="stopped again after being started by hand"):
        m.homebrew_setup_installs_control_center(_context())
    assert calls == [m.BREW_PROBE, m.MANUAL_START, m.BREW_PROBE, m.BREW_DIAGNOSTICS]


def test_homebrew_step_times_out_with_unit_state_and_journal(monkeypatch):
    waiting = SKIPPED.replace("preinstall.ActiveState=inactive", "preinstall.ActiveState=activating")
    fake, calls = _ssh({"uptime_s": (waiting, 0), "who owns": ("== brew-preinstall.service (user)\njournal tail", 0)})
    monkeypatch.setattr(m, "run_ssh", fake)
    monkeypatch.setattr(m, "INSTALL_DEADLINE", 0)
    with pytest.raises(AssertionError, match="not installed within 0s") as raised:
        m.homebrew_setup_installs_control_center(_context())
    assert "brew-preinstall=loaded/activating/dead/success" in str(raised.value)
    assert "journal tail" in str(raised.value)
    assert m.MANUAL_START not in calls


@pytest.mark.parametrize("change,reason", [
    ({"setup.LoadState": "masked"}, "brew-setup.service is masked, so this run's e2e.yml did not prepare the guest"),
    ({"setup.LoadState": "not-found"}, "this image ships no brew-setup.service"),
    ({"preinstall.LoadState": "not-found"}, "brew-preinstall.service is not-found for the test user"),
    ({"preinstall.LoadState": "masked"}, "brew-preinstall.service is masked for the test user"),
    ({"setup.ActiveState": "failed"}, "brew-setup.service failed"),
    ({"brew": "no"}, "brew-setup.service is not running and has not unpacked Homebrew"),
    ({"preinstall.ActiveState": "active"}, "brew-preinstall.service finished without installing the launcher"),
])
def test_homebrew_step_fails_at_once_when_waiting_cannot_help(monkeypatch, change, reason):
    state = "\n".join(f"{key}={value}" for key, value in {**m._key_values(SKIPPED), **change}.items())
    fake, calls = _ssh({"uptime_s": (state, 0), "who owns": ("DIAGNOSTICS", 0)})
    monkeypatch.setattr(m, "run_ssh", fake)
    with pytest.raises(AssertionError, match=reason):
        m.homebrew_setup_installs_control_center(_context())
    assert calls == [m.BREW_PROBE, m.BREW_DIAGNOSTICS]
    assert m.blocked_reason(m._key_values(SKIPPED)) == ""


def test_control_center_is_installed(monkeypatch):
    monkeypatch.setattr(m, "run_ssh", _ssh({"test -x": ("", 0)})[0])
    m.control_center_is_installed(_context())
    monkeypatch.setattr(m, "run_ssh", _ssh({"test -x": ("", 1)})[0])
    with pytest.raises(AssertionError, match="chairlift-wrapper is missing"):
        m.control_center_is_installed(_context())


def test_launch_stops_the_old_instance_and_passes_arguments_and_environment(monkeypatch):
    stopped, launched = [], []
    monkeypatch.setattr(m, "tree", _tree())
    monkeypatch.setattr(m, "stop_app_instances", stopped.append)
    monkeypatch.setattr(m, "launch_background", lambda targets, env=None: launched.append((targets, env)) or "command:x")
    monkeypatch.setattr(m, "run_ssh", _ssh({})[0])
    context = _context()
    m.launch_control_center_in_preview_mode(context)
    m.launch_control_center_with_the_action_journal(context)
    assert stopped == ["chairlift", "chairlift"]
    assert launched[0] == ((("command", f"{m.LAUNCHER} --dry-run"),), None)
    assert launched[1] == ((("command", m.LAUNCHER),), {"CHAIRLIFT_ACTION_JOURNAL": "/tmp/results/chairlift-action-journal.jsonl"})
    assert context.chairlift_launch_target == "command:x"


def test_launch_needs_atspi():
    with pytest.raises(AssertionError, match="AT-SPI unavailable"):
        m.launch_control_center_in_preview_mode(_context())


def test_window_lookup_requires_the_title_and_a_populated_tree(monkeypatch):
    app, window, _ = _app()
    monkeypatch.setattr(m, "tree", _tree(Node("application", "gnome-shell"), app))
    assert m._window() is window
    assert m.sidebar_pages(window) == ["Updates", "Apps", "Help"]

    monkeypatch.setattr(m, "tree", _tree(Node("application", "Control Center", [Node("frame", "Control Center")])))
    with pytest.raises(LookupError, match="no populated 'Control Center' window"):
        m._window()
    monkeypatch.setattr(m, "tree", _tree(Node("application", "gnome-control-center")))
    with pytest.raises(LookupError, match="not an AT-SPI application; found \\['gnome-control-center'\\]"):
        m._window()


def test_sidebar_pages_is_best_effort(capsys):
    assert m.sidebar_pages(_app(sidebar=False)[1]) == []
    broken = SimpleNamespace(findChildren=MagicMock(side_effect=RuntimeError("bus dropped")))
    assert m.sidebar_pages(broken) == []
    assert "sidebar not read: bus dropped" in capsys.readouterr().out
    assert m._label(Node("list item")) == ""


def test_window_step_records_what_it_found(monkeypatch):
    app, _, _ = _app()
    monkeypatch.setattr(m, "tree", _tree(app))
    monkeypatch.setattr(m, "run_ssh", _ssh({"NameHasOwner": ("(true,)", 0)})[0])
    context = _context()
    context.chairlift_launched = m.time.monotonic()
    m.control_center_window_is_accessible(context)
    assert "window 'Control Center' (role 'frame') shown" in context.chairlift_window_report
    assert "AT-SPI application name 'chairlift'" in context.chairlift_window_report
    assert "sidebar pages: ['Updates', 'Apps', 'Help']" in context.chairlift_window_report

    monkeypatch.setattr(m, "run_ssh", _ssh({"NameHasOwner": ("(false,)", 0)})[0])
    with pytest.raises(AssertionError, match="no process owns the session-bus name io.projectbluefin.chairlift"):
        m.control_center_window_is_accessible(context)


def test_poll_reports_the_last_error_at_its_deadline():
    with pytest.raises(AssertionError, match="thing not reached within 0s: LookupError: nope"):
        m._poll("thing", 0, MagicMock(side_effect=LookupError("nope")))
    with pytest.raises(AssertionError, match="probe returned nothing"):
        m._poll("thing", 0, lambda: None)


def test_preview_step_reads_the_process_arguments(monkeypatch, capsys):
    context = _context()
    context.chairlift_window_report = "REPORT"
    fake, calls = _ssh({"pgrep": ("4242", 0), "cmdline": (f"{m.BINARY}\n--dry-run", 0)})
    monkeypatch.setattr(m, "run_ssh", fake)
    m.control_center_is_running_in_preview_mode(context)
    assert f"CHAIRLIFT preview: preview mode ({m.BINARY} --dry-run): REPORT" in capsys.readouterr().out
    assert "/proc/4242/cmdline" in calls[-1]

    monkeypatch.setattr(m, "run_ssh", _ssh({"pgrep": ("4242", 0), "cmdline": (m.BINARY, 0)})[0])
    with pytest.raises(AssertionError, match="not in preview mode"):
        m.control_center_is_running_in_preview_mode(context)
    monkeypatch.setattr(m, "run_ssh", _ssh({"pgrep": ("4242\n4300", 0)})[0])
    with pytest.raises(AssertionError, match="expected one chairlift process"):
        m.gui_pid(context)


def test_close_waits_for_the_process_to_exit(monkeypatch):
    stopped = []
    monkeypatch.setattr(m, "stop_app_instances", stopped.append)
    monkeypatch.setattr(m, "run_ssh", _ssh({"pgrep": [("4242", 0), ("", 1)]})[0])
    m.close_control_center(_context())
    assert stopped == ["chairlift"]


def test_dump_tree_writes_the_subtree_or_the_reason(monkeypatch, tmp_path):
    context = _context(tmp_path)
    assert m.dump_tree(context, "none") is None
    monkeypatch.setattr(m, "tree", _tree(_app()[0]))
    text = (tmp_path / "chairlift_atspi_tree_preview.txt")
    assert m.dump_tree(context, "preview") == str(text)
    assert "list item name='Automatic Updates'" in text.read_text()
    monkeypatch.setattr(m, "tree", _tree())
    m.dump_tree(context, "preview")
    assert "Control Center not in the AT-SPI tree" in text.read_text()


@pytest.mark.parametrize("enabled,active,expected", [
    ("enabled", "active", "on"),
    ("enabled-runtime", "active", "on"),
    ("enabled", "inactive", "off"),
    ("masked", "inactive", "off"),
    ("disabled", "active", "off"),
    ("", "inactive", "unavailable"),
    ("not-found", "", "unavailable"),
])
def test_classify_timer_matches_chairlift(enabled, active, expected):
    assert m.classify_timer(enabled, active) == expected


def test_timer_state_and_expected_action(monkeypatch):
    monkeypatch.setattr(m, "run_ssh", _ssh({"is-enabled": ("enabled=masked\nactive=inactive\nresume=masked", 0)})[0])
    assert m.timer_state(_context()) == "off"
    assert m.expected_action("on") == "auto-updates-disable"
    assert m.expected_action("off") == "auto-updates-enable"


def _journal(*entries):
    return "\n".join(json.dumps(entry) for entry in entries)


ASKED = {"seq": 1, "action": "auto-updates-disable", "suppressed": "no",
         "would_run": ["pkexec", "/usr/bin/chairlift-helper", "auto-updates-disable"]}
DONE = {"seq": 2, "action": "auto-updates-disable", "outcome": "succeeded",
        "executed": [["systemctl", "disable", "--now", "uupd.timer"]]}


def test_read_journal_skips_partial_lines(monkeypatch):
    text = _journal(ASKED, DONE) + '\n{"seq": 3, "action": "auto-upd\n[1]\n'
    monkeypatch.setattr(m, "run_ssh", _ssh({"chairlift-action-journal.jsonl": (text, 0)})[0])
    entries = m.read_journal(_context())
    assert entries == [ASKED, DONE]
    assert m.attempts(entries, "auto-updates-disable") == [ASKED]
    assert m.outcomes(entries, "auto-updates-disable") == [DONE]
    assert m.outcomes(entries, "auto-updates-enable") == []


def test_agent_status_helpers(monkeypatch):
    context = _context()
    monkeypatch.setattr(m, "run_ssh", _ssh({"agent.status": ("registered\nanswered 1\nanswered 2", 0)})[0])
    assert m.agent_registered(context) is True
    assert m.agent_prompts(context) == 2
    monkeypatch.setattr(m, "run_ssh", _ssh({"agent.status": ("", 1)})[0])
    assert m.agent_registered(context) is False
    monkeypatch.setattr(m, "run_ssh", _ssh({"agent.status": ("error: pkttyagent could not be started", 0)})[0])
    with pytest.raises(LookupError, match="could not be started"):
        m.agent_registered(context)


READY = ("password_file=yes\npassword_mode=600 bluefin-test\npkttyagent=yes\npkexec=yes\npython3=yes\n"
         "helper=yes\nwheel=yes\nshadow_scheme=$6$")


def test_prerequisites_record_the_starting_state(monkeypatch, capsys):
    context = _context()
    monkeypatch.setattr(m, "run_ssh", _ssh({
        "password_file": (READY, 0), "is-enabled": ("enabled=enabled\nactive=active\nresume=enabled", 0),
    })[0])
    m.admin_password_prompt_can_be_answered(context)
    assert (context.chairlift_initial, context.chairlift_flips) == ("on", [])
    assert "shadow scheme '$6$'; automatic updates start on" in capsys.readouterr().out
    context.scenario.skip.assert_not_called()


def test_prerequisites_fail_without_the_workflow_step_and_skip_without_the_timer(monkeypatch):
    context = _context()
    monkeypatch.setattr(m, "run_ssh", _ssh({"password_file": (READY.replace("password_file=yes", "password_file=no"), 0)})[0])
    with pytest.raises(AssertionError, match=r"missing: \['password_file'\].*e2e.yml"):
        m.admin_password_prompt_can_be_answered(context)
    monkeypatch.setattr(m, "run_ssh", _ssh({"password_file": (READY, 0), "is-enabled": ("enabled=\nactive=inactive", 0)})[0])
    m.admin_password_prompt_can_be_answered(context)
    context.scenario.skip.assert_called_once()
    assert not hasattr(context, "chairlift_initial")


@pytest.mark.parametrize("answer", [("", 255), ("ssh: connect to host 127.0.0.1 port 2222: refused", 255)])
def test_prerequisites_fail_when_the_timer_cannot_be_read(monkeypatch, answer):
    # An unreadable probe must not look like "uupd.timer is not installed".
    context = _context()
    monkeypatch.setattr(m, "run_ssh", _ssh({"password_file": (READY, 0), "is-enabled": answer})[0])
    with pytest.raises(AssertionError, match="could not read uupd.timer over SSH"):
        m.admin_password_prompt_can_be_answered(context)
    context.scenario.skip.assert_not_called()


def test_agent_is_started_in_the_guest_for_the_gui_pid(monkeypatch):
    context = _context()
    fake, calls = _ssh({
        "pgrep": ("4242", 0), "cmdline": (m.BINARY, 0), "systemd-run": ("", 0),
        "cat ": [("", 1), ("registered", 0)],
    })
    monkeypatch.setattr(m, "run_ssh", fake)
    m.start_the_password_agent(context)
    launch = next(call for call in calls if "systemd-run" in call)
    assert f"python3 {m.AGENT_SCRIPT} --process 4242 --password-file {m.PASSWORD_FILE}" in launch
    assert m.AGENT_SCRIPT.endswith("tests/chairlift/polkit_tty_agent.py")
    assert "--stop-file /tmp/chairlift-polkit-agent.stop --timeout 420" in launch
    assert context.chairlift_agent_started is True

    monkeypatch.setattr(m, "run_ssh", _ssh({"pgrep": ("4242", 0), "cmdline": (f"{m.BINARY}\n--dry-run", 0)})[0])
    with pytest.raises(AssertionError, match="started Control Center in preview mode"):
        m.start_the_password_agent(context)


def test_stop_password_agent(monkeypatch):
    context = _context()
    fake, calls = _ssh({"touch": ("", 0), "cat ": ("registered\nstopped prompts=1", 0)})
    monkeypatch.setattr(m, "run_ssh", fake)
    m.stop_password_agent(context)
    assert calls == []
    context.chairlift_agent_started = True
    m.stop_password_agent(context)
    assert calls[0] == "touch /tmp/chairlift-polkit-agent.stop"
    assert context.chairlift_agent_started is False


def test_row_switch_is_found_from_the_row_title():
    _, window, switch = _app()
    assert m._row_switch(window, "Automatic Updates") is switch
    with pytest.raises(LookupError, match="no showing switch in a row titled 'Docker'"):
        m._row_switch(window, "Docker")
    plain = Node("frame", "Control Center", [Node("list item", "Automatic Updates", [Node("label", "x")])])
    with pytest.raises(LookupError):
        m._row_switch(plain, "Automatic Updates")
    orphan = Node("frame", "Control Center", [Node("label", "Automatic Updates")])
    orphan.parent = None
    with pytest.raises(LookupError):
        m._row_switch(orphan, "Automatic Updates")


def test_activate_uses_the_first_known_action():
    switch = Node("switch", actions=("toggle", "activate"))
    assert m.activate(switch) == "activate"
    assert switch.done == ["activate"]
    with pytest.raises(AssertionError, match="has no primary action; has \\['jump'\\]"):
        m.activate(Node("switch", "x", actions=("jump",)))


def test_flip_waits_for_the_switch_to_agree_with_the_system(monkeypatch, capsys):
    app, _, switch = _app()
    monkeypatch.setattr(m, "tree", _tree(app))
    monkeypatch.setattr(m, "run_ssh", _ssh({
        "is-enabled": ("enabled=enabled\nactive=active", 0), "agent.status": ("registered", 0),
    })[0])
    context = _context()
    context.chairlift_flips = []
    m.flip_the_switch(context, "Automatic Updates")
    assert switch.done == ["toggle"]
    assert context.chairlift_flips[0]["action"] == "auto-updates-disable"
    assert context.chairlift_flips[0]["prompts_before"] == 0
    assert "flipped 'Automatic Updates' from on with the AT-SPI action 'toggle'" in capsys.readouterr().out

    switch.checked = False  # the window disagrees with systemd: never flipped
    monkeypatch.setattr(m, "ROW_TIMEOUT", 0)
    with pytest.raises(AssertionError, match="switch showing on not reached"):
        m.flip_the_switch(context, "Automatic Updates")
    monkeypatch.setattr(m, "run_ssh", _ssh({"is-enabled": ("enabled=\nactive=", 0)})[0])
    with pytest.raises(AssertionError, match="uupd.timer is unavailable"):
        m.flip_the_switch(context, "Automatic Updates")


def _flip_context(action="auto-updates-disable"):
    context = _context()
    context.chairlift_flips = [
        {"action": action, "prompts_before": 0, "started": m.time.monotonic()},
        {"action": "auto-updates-enable", "prompts_before": 1, "started": m.time.monotonic()},
    ]
    return context


BANNER = "\x1b[1;31m==== AUTHENTICATING FOR io.projectbluefin.chairlift.ublue.auto-updates-disable ====\nPassword: "
TRANSCRIPT = "chairlift-polkit-agent.txt 2>/dev/null"


def test_change_is_proved_by_the_journal_and_a_real_prompt(monkeypatch, capsys):
    monkeypatch.setattr(m, "run_ssh", _ssh({
        "cat /tmp/results/chairlift-action-journal.jsonl": (_journal(ASKED, DONE), 0),
        "agent.status": ("registered\nanswered 1", 0),
        TRANSCRIPT: (BANNER, 0),
    })[0])
    m.journal_records_the_change(_flip_context())
    out = capsys.readouterr().out
    assert "CHAIRLIFT admin: auto-updates-disable outcome=succeeded" in out
    assert "password prompts pkttyagent answered for it: 1" in out


def test_undo_may_succeed_without_a_second_prompt(monkeypatch, capsys):
    enable = [{**ASKED, "action": "auto-updates-enable",
               "would_run": ["pkexec", "/usr/bin/chairlift-helper", "auto-updates-enable"]},
              {**DONE, "action": "auto-updates-enable"}]
    monkeypatch.setattr(m, "run_ssh", _ssh({
        "cat /tmp/results/chairlift-action-journal.jsonl": (_journal(ASKED, DONE, *enable), 0),
        "agent.status": ("registered\nanswered 1", 0),
    })[0])
    m.journal_records_the_undo(_flip_context())
    assert "CHAIRLIFT admin undo: auto-updates-enable outcome=succeeded" in capsys.readouterr().out


@pytest.mark.parametrize("journal,status,message", [
    ([ASKED, {**DONE, "outcome": "refused", "exit_code": 127}], "registered\nanswered 1", "did not succeed"),
    ([ASKED, DONE], "registered", "pkttyagent answered no password prompt"),
    ([{**ASKED, "suppressed": "dry-run"}, DONE], "registered\nanswered 1", "not journalled as a real pkexec run"),
    ([DONE], "registered\nanswered 1", "not journalled as a real pkexec run"),
    # A prompt was answered, but for another action of the same process.
    ([ASKED, DONE], "registered\nanswered 1", "but not one for io.projectbluefin.chairlift.ublue.auto-updates-disable"),
])
def test_change_fails_with_the_agent_evidence(monkeypatch, journal, status, message):
    other = BANNER.replace("auto-updates-disable", "auto-updates-enable")
    monkeypatch.setattr(m, "run_ssh", _ssh({
        "== polkit agent status": ("TRANSCRIPT", 0),
        "cat /tmp/results/chairlift-action-journal.jsonl": (_journal(*journal), 0),
        "agent.status": (status, 0),
        TRANSCRIPT: (other if "but not one" in message else BANNER, 0),
    })[0])
    with pytest.raises(AssertionError, match=message):
        m.journal_records_the_change(_flip_context())


def test_change_times_out_with_the_transcript_and_the_shell_dialog_hint(monkeypatch):
    monkeypatch.setattr(m, "ACTION_TIMEOUT", 0)
    monkeypatch.setattr(m, "run_ssh", _ssh({
        "== polkit agent status": ("registered\n== pkttyagent transcript (password replaced)", 0),
        "cat /tmp/results/chairlift-action-journal.jsonl": (_journal(ASKED), 0),
    })[0])
    with pytest.raises(AssertionError, match="outcome for auto-updates-disable not reached") as raised:
        m.journal_records_the_change(_flip_context())
    assert "pkttyagent transcript (password replaced)" in str(raised.value)
    assert "GNOME Shell's own dialog probably took it" in str(raised.value)


def test_system_state_steps(monkeypatch, capsys):
    context = _context()
    context.chairlift_initial = "on"
    monkeypatch.setattr(m, "run_ssh", _ssh({"is-enabled": ("enabled=masked\nactive=inactive\nresume=masked", 0)})[0])
    m.automatic_updates_are_flipped(context)
    assert "automatic updates off: {'enabled': 'masked'" in capsys.readouterr().out
    monkeypatch.setattr(m, "STATE_TIMEOUT", 0)
    with pytest.raises(AssertionError, match="uupd.timer reading on not reached.*systemd says"):
        m.automatic_updates_are_back(context)
    context.chairlift_initial = "off"
    m.automatic_updates_are_back(context)
    with pytest.raises(AssertionError, match="uupd.timer reading on not reached"):
        m.automatic_updates_are_flipped(context)


def test_restore_automatic_updates(monkeypatch, capsys):
    context = _context()
    fake, calls = _ssh({"is-enabled": ("enabled=masked\nactive=inactive", 0)})
    monkeypatch.setattr(m, "run_ssh", fake)
    m.restore_automatic_updates(context)  # the scenario never recorded a starting state
    context.chairlift_initial = "off"
    m.restore_automatic_updates(context)  # already as it was
    assert not any("sudo" in call for call in calls)

    context.chairlift_initial = "on"
    fake, calls = _ssh({
        "sudo -n systemctl unmask": ("", 0),
        "is-enabled": [("enabled=masked\nactive=inactive", 0), ("enabled=enabled\nactive=active", 0)],
    })
    monkeypatch.setattr(m, "run_ssh", fake)
    m.restore_automatic_updates(context)
    assert m.RESTORE["on"] in calls
    assert "restored to on with sudo" in capsys.readouterr().out

    monkeypatch.setattr(m, "run_ssh", _ssh({
        "sudo -n systemctl unmask": ("denied", 1), "is-enabled": ("enabled=masked\nactive=inactive", 0),
    })[0])
    with pytest.raises(AssertionError, match="could not restore automatic updates to on"):
        m.restore_automatic_updates(context)
    assert "mask --now uupd-resume.timer" in m.RESTORE["off"]


# --- The first-login Homebrew install settles -------------------------------

PREINSTALL_DONE = "\n".join([
    "uptime_s=600", "LoadState=loaded", "ActiveState=active", "SubState=exited", "Result=success",
    "ConditionResult=yes", "ExecMainCode=1", "ExecMainStatus=0", "NRestarts=0", "Job=",
    "InactiveExitTimestampMonotonic=30000000", "ActiveEnterTimestampMonotonic=190000000",
    "InactiveEnterTimestampMonotonic=0",
])
PREINSTALL_RESTARTING = PREINSTALL_DONE.replace("ActiveState=active", "ActiveState=activating").replace(
    "SubState=exited", "SubState=auto-restart").replace("Result=success", "Result=exit-code").replace(
    "ExecMainStatus=0", "ExecMainStatus=1").replace("NRestarts=0", "NRestarts=1")
PREINSTALL_FAILED = PREINSTALL_RESTARTING.replace("ActiveState=activating", "ActiveState=failed").replace(
    "SubState=auto-restart", "SubState=failed").replace("NRestarts=1", "NRestarts=2")


@pytest.mark.parametrize("change,settled", [
    ({}, True),
    ({"ActiveState": "failed", "SubState": "failed"}, True),
    ({"ActiveState": "inactive", "SubState": "dead"}, True),
    ({"ActiveState": "activating", "SubState": "start"}, False),
    ({"ActiveState": "activating", "SubState": "auto-restart"}, False),
    ({"ActiveState": "inactive", "SubState": "auto-restart"}, False),
    ({"ActiveState": "inactive", "SubState": "dead", "Job": "7"}, False),
    ({"ActiveState": "deactivating", "SubState": "stop"}, False),
])
def test_preinstall_settled(change, settled):
    assert m.preinstall_settled({**m._key_values(PREINSTALL_DONE), **change}) is settled


@pytest.mark.parametrize("change,settled,ok,words", [
    ({}, True, True, "finished successfully"),
    ({"ActiveState": "failed", "Result": "start-limit-hit"}, True, False, "failed for good (result start-limit-hit)"),
    ({"ActiveState": "inactive", "SubState": "dead", "ConditionResult": "no"}, True, False, "never ran: its start condition"),
    ({"ActiveState": "inactive", "SubState": "dead"}, True, False, "ended inactive/dead (result success)"),
    ({"ActiveState": "activating", "SubState": "auto-restart"}, False, False, "still activating/auto-restart when the wait ended"),
    ({"LoadState": "not-found"}, True, False, "the unit is not-found for the test user"),
])
def test_preinstall_outcome(change, settled, ok, words):
    got_ok, got_words = m.preinstall_outcome({**m._key_values(PREINSTALL_DONE), **change}, settled)
    assert got_ok is ok and got_words.startswith(words)


def test_describe_preinstall_names_the_exit_status():
    assert m.describe_preinstall(m._key_values(PREINSTALL_RESTARTING)) == (
        "activating/auto-restart result=exit-code exit_status=1 (exited) restarts=1 condition=yes"
    )
    assert "exit_status=? (?)" in m.describe_preinstall({})
    assert "(9)" in m.describe_preinstall({"ExecMainCode": "9"})


def test_wait_returns_at_once_when_settled(monkeypatch, capsys):
    fake, calls = _ssh({"brew-preinstall.service -p": (PREINSTALL_DONE, 0)})
    monkeypatch.setattr(m, "run_ssh", fake)
    context = _context()
    m.wait_for_the_preinstall_to_settle(context)
    assert calls == [m.PREINSTALL_PROBE]
    assert context.chairlift_preinstall["settled"] is True
    assert "brew-preinstall.service active/exited result=success exit_status=0 (exited)" in capsys.readouterr().out


def test_wait_polls_through_a_restart_until_it_gives_up(monkeypatch):
    fake, calls = _ssh({"brew-preinstall.service -p": [
        (PREINSTALL_RESTARTING, 0), (PREINSTALL_RESTARTING, 0), (PREINSTALL_FAILED, 0)]})
    monkeypatch.setattr(m, "run_ssh", fake)
    context = _context()
    m.wait_for_the_preinstall_to_settle(context)
    assert len(calls) == 3
    assert context.chairlift_preinstall["state"]["ActiveState"] == "failed"


def test_wait_is_bounded_and_does_not_fail_on_a_unit_still_restarting(monkeypatch):
    monkeypatch.setattr(m, "SETTLE_DEADLINE", 0)
    monkeypatch.setattr(m, "run_ssh", _ssh({"brew-preinstall.service -p": (PREINSTALL_RESTARTING, 0)})[0])
    context = _context()
    m.wait_for_the_preinstall_to_settle(context)
    assert context.chairlift_preinstall["settled"] is False


@pytest.mark.parametrize("answer", [("", 255), ("ssh: connect refused", 0)])
def test_wait_fails_when_the_unit_cannot_be_read(monkeypatch, answer):
    monkeypatch.setattr(m, "run_ssh", _ssh({"brew-preinstall.service -p": answer})[0])
    with pytest.raises(AssertionError, match="could not read brew-preinstall.service over SSH"):
        m.wait_for_the_preinstall_to_settle(_context())


def _recorded(tmp_path, state, settled=True):
    context = _context(tmp_path)
    context.chairlift_preinstall = {"state": m._key_values(state), "settled": settled, "waited": 42.4}
    return context


def test_record_writes_state_exit_status_and_journal_and_passes(monkeypatch, tmp_path, capsys):
    journal = "\n".join(f"[  {i}.0] brew-preinstall[9]: line {i}" for i in range(40))
    fake, calls = _ssh({"journalctl": (journal, 0)})
    monkeypatch.setattr(m, "run_ssh", fake)
    m.record_how_the_preinstall_ended(_recorded(tmp_path, PREINSTALL_DONE))
    assert calls == [m.PREINSTALL_JOURNAL]
    text = (tmp_path / "chairlift-brew-preinstall.txt").read_text()
    assert text.startswith("finished successfully; active/exited result=success exit_status=0 (exited)")
    assert "last started boot+30s, last finished boot+190s, stopped never" in text
    assert "settled after 42s of waiting, at uptime 600s" in text
    assert "== journal of brew-preinstall.service (last 80 lines, rc=0)" in text and "line 0" in text
    out = capsys.readouterr().out
    assert "CHAIRLIFT brew-preinstall: finished successfully" in out
    assert out.count("CHAIRLIFT brew-preinstall journal: ") == m.JOURNAL_LINES_IN_LOG
    assert ": line 39\n" in out and ": line 9\n" not in out and "KNOWN GAP" not in out


@pytest.mark.parametrize("state,settled,words", [
    (PREINSTALL_FAILED, True, "failed for good (result exit-code)"),
    (PREINSTALL_RESTARTING, False, "still activating/auto-restart"),
])
def test_record_reports_a_bad_end_as_a_known_gap_without_failing(monkeypatch, tmp_path, capsys, state, settled, words):
    monkeypatch.setattr(m, "run_ssh", _ssh({"journalctl": ("tap failed", 0)})[0])
    m.record_how_the_preinstall_ended(_recorded(tmp_path, state, settled))
    out = capsys.readouterr().out
    assert f"KNOWN GAP, recorded and not failed: brew-preinstall.service {words}" in out
    assert "exit_status=1 (exited)" in (tmp_path / "chairlift-brew-preinstall.txt").read_text()
    if not settled:
        assert "not settled after 42s of waiting" in out


def test_journal_command_matches_the_test_users_unit_not_roots():
    # journalctl --user-unit= adds a _UID= match for whoever runs journalctl,
    # so under sudo it matched uid 0 and printed "-- No entries --" (#1326).
    command = m.preinstall_journal_command()
    assert command == m.PREINSTALL_JOURNAL
    assert "--user-unit" not in command
    assert command.startswith("sudo -n journalctl -b --no-pager -o short-monotonic -n 80 ")
    unit = "brew-preinstall.service"
    words = shlex.split(command)
    matches = words[words.index("80") + 1:words.index("2>&1")]
    assert matches == [
        f"_SYSTEMD_USER_UNIT={unit}", "_UID=$(id -u)", "+", f"USER_UNIT={unit}", "_UID=$(id -u)",
    ]
    # id -u runs in the SSH user's (the test user's) shell, before sudo.
    expanded = subprocess.run(
        ["bash", "-c", command.replace("sudo -n journalctl", "printf '%s\\n'").replace(" 2>&1", "")],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert expanded[-1] == f"_UID={os.getuid()}" and expanded[-2] == f"USER_UNIT={unit}"


def test_record_says_so_when_the_journal_is_empty(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(m, "run_ssh", _ssh({"journalctl": ("-- No entries --\n", 0)})[0])
    m.record_how_the_preinstall_ended(_recorded(tmp_path, PREINSTALL_FAILED))
    out = capsys.readouterr().out
    assert "CHAIRLIFT brew-preinstall journal: EMPTY: no journal lines for brew-preinstall.service" in out
    assert "-- No entries --" not in out
    assert "EMPTY: no journal lines" in (tmp_path / "chairlift-brew-preinstall.txt").read_text()


def test_record_fails_on_an_unreadable_journal_after_writing_the_report(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(m, "run_ssh", _ssh({"journalctl": ("sudo: a password is required", 1)})[0])
    with pytest.raises(AssertionError, match=r"could not read the journal of brew-preinstall.service \(rc=1\)"):
        m.record_how_the_preinstall_ended(_recorded(tmp_path, PREINSTALL_DONE))
    text = (tmp_path / "chairlift-brew-preinstall.txt").read_text()
    assert "rc=1)\nsudo: a password is required" in text
    assert "EMPTY" not in capsys.readouterr().out
