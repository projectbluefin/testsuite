"""The baseline must reject substitute systems and accessibility fallbacks."""
from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest
import yaml

from tests.shared.gnomeos_canary import require_gnomeos_wayland

IDENTITY = 'ID=org.gnome.os\nNAME="GNOME OS"\nGNOMEOS_COMMIT=abc\nIMAGE_VERSION=nightly.1\n'
ENV = {
    "XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0",
    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1001/bus",
    "AT_SPI_BUS_ADDRESS": "unix:path=/run/user/1001/at-spi/bus",
}


def test_genuine_identity():
    assert require_gnomeos_wayland(IDENTITY, ENV)["NAME"] == "GNOME OS"


@pytest.mark.parametrize("key", ENV)
def test_missing_session_evidence_fails(key):
    env = ENV.copy()
    del env[key]
    with pytest.raises(AssertionError):
        require_gnomeos_wayland(IDENTITY, env)


@pytest.mark.parametrize("identity", ["", IDENTITY.replace("org.gnome.os", "dakota"),
                                    IDENTITY.replace("GNOMEOS_COMMIT=abc", "GNOMEOS_COMMIT="),
                                    IDENTITY.replace("IMAGE_VERSION=nightly.1", "IMAGE_VERSION=")])
def test_unknown_or_substitute_identity_fails(identity):
    with pytest.raises(AssertionError):
        require_gnomeos_wayland(identity, ENV)


def test_accessibility_fallback_fails():
    with pytest.raises(AssertionError, match="fallback"):
        require_gnomeos_wayland(IDENTITY, {**ENV, "AT_SPI_BUS_ADDRESS": ENV["DBUS_SESSION_BUS_ADDRESS"]})


def test_xorg_fails():
    with pytest.raises(AssertionError, match="Wayland"):
        require_gnomeos_wayland(IDENTITY, {**ENV, "XDG_SESSION_TYPE": "x11"})


def test_canary_caller_uses_strict_gate_and_preserves_evidence():
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/gnomeos-canary.yml").read_text())
    steps = workflow["jobs"]["canary"]["steps"]
    action_step = next(s for s in steps if s.get("uses", "").endswith("/gnome-e2e"))
    assert action_step["with"]["suite"] == "gnomeos-canary"
    action = yaml.safe_load((root / ".github/actions/gnome-e2e/action.yml").read_text())
    gate = next(s for s in action["runs"]["steps"] if s["name"] == "Gate extension-validation run")
    assert "always()" in gate["if"] and "inputs.suite == 'gnomeos-canary'" in gate["if"]
    upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["if"] == "always()"
    assert "bootc-install.log" in upload["with"]["path"]


@pytest.mark.parametrize("process_rc,scenario_status,expected_rc", [
    ("0", "passed", 0), ("1", "passed", 1), ("", "passed", 1),
    ("0", "skipped", 1), ("0", "hook_error", 1),
])
def test_actual_gate_requires_process_and_scenarios(tmp_path, process_rc, scenario_status, expected_rc):
    root = Path(__file__).resolve().parents[2]
    scripts = tmp_path / "_testsuite/scripts"
    scripts.mkdir(parents=True)
    for name in ("extension_validation.py", "e2e_summary.py"):
        shutil.copy(root / "scripts" / name, scripts / name)
    results = tmp_path / "results"
    results.mkdir()
    (results / "results.json").write_text(json.dumps([{
        "elements": [{"type": "scenario", "status": scenario_status}]
    }]))
    action = yaml.safe_load((root / ".github/actions/gnome-e2e/action.yml").read_text())
    gate = next(s for s in action["runs"]["steps"] if s["name"] == "Gate extension-validation run")
    result = subprocess.run(["bash", "-e", "-c", gate["run"]], cwd=tmp_path,
                            env={**os.environ, "GNOME_E2E_BEHAVE_RC": process_rc},
                            capture_output=True, text=True)
    assert result.returncode == expected_rc, result.stdout + result.stderr


class FakePonytail:
    fail_at = None
    # How the canary window behaves: "focused" when mapped, "escape" to take
    # focus once Escape leaves the overview, "click" to take focus on the
    # first virtual click, "never" to stay unfocused, "absent" to never be
    # listed by the shell.
    window = "focused"
    instances = []

    def __init__(self):
        if self.fail_at == "init":
            raise RuntimeError("no ponytail daemon")
        self.connected = None
        self.disconnected = False
        self.keysyms = []
        self.clicks = []
        self.control = []
        self.windows = []
        self.monitor_connected = False
        self.focused = self.window == "focused"
        FakePonytail.instances.append(self)

    @property
    def window_list(self):
        if self.fail_at == "wait":
            raise RuntimeError("window never appeared")
        if self.window == "absent":
            return []
        return [{"id": 7, "title": "GNOME OS input canary", "width": 480, "height": 157,
                 "has-focus": self.focused}]

    def getWindowId(self, title, want_focus=False):
        return 7

    def generateButtonEvent(self, button, x=None, y=None):
        self.clicks.append((button, x, y))
        if self.window == "click":
            self.focused = True

    def connectWindow(self, window_id):
        self.connected = window_id
        self.windows.append(window_id)

    def connectMonitor(self, monitor=""):
        self.connected = monitor
        self.monitor_connected = True

    def generateKeysymEvent(self, keysym):
        if keysym >= 0xFF00:  # control keys (Escape) aren't typed text
            self.control.append(keysym)
            if self.window == "escape":
                self.focused = True
            return
        self.keysyms.append(keysym)

    def disconnect(self):
        self.disconnected = True


class FakeChild:
    def __init__(self, *args, **kwargs):
        self.terminated = self.waited = False
        FakeChild.last = self

    def terminate(self):
        self.terminated = True

    def wait(self, timeout):
        self.waited = True


@pytest.fixture
def probe_env(tmp_path, monkeypatch):
    """Run probe() with the desktop, Ponytail and AT-SPI replaced by fakes."""
    import sys
    import types
    from tests.shared import gnomeos_canary

    FakePonytail.fail_at = None
    FakePonytail.window = "focused"
    FakePonytail.instances = []
    state = {"readback": lambda expected: expected, "commands": []}
    node = types.SimpleNamespace(name=gnomeos_canary.ENTRY_NAME, text="")

    def find_children(predicate):
        keysyms = FakePonytail.instances[-1].keysyms
        node.text = state["readback"]("".join(map(chr, keysyms)))
        return [n for n in (node,) if predicate(n)]

    dogtail = types.ModuleType("dogtail")
    dogtail.tree = types.SimpleNamespace(root=types.SimpleNamespace(findChildren=find_children))
    ponytail_pkg = types.ModuleType("ponytail")
    ponytail_mod = types.ModuleType("ponytail.ponytail")
    ponytail_mod.Ponytail = FakePonytail
    ponytail_pkg.ponytail = ponytail_mod
    monkeypatch.setitem(sys.modules, "dogtail", dogtail)
    monkeypatch.setitem(sys.modules, "ponytail", ponytail_pkg)
    monkeypatch.setitem(sys.modules, "ponytail.ponytail", ponytail_mod)

    (tmp_path / "os-release").write_text(IDENTITY)
    (tmp_path / "mutter-version.txt").write_text("49.0\n")
    redirects = {"/usr/lib/os-release": tmp_path / "os-release",
                 "/opt/gnomeos-harness/mutter-version.txt": tmp_path / "mutter-version.txt"}
    monkeypatch.setattr(gnomeos_canary, "Path", lambda p: Path(redirects.get(str(p), p)))
    monkeypatch.setattr(gnomeos_canary, "RESULTS", tmp_path / "results")
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(gnomeos_canary.subprocess, "Popen", FakeChild)
    clock = iter(range(0, 10_000))
    monkeypatch.setattr(gnomeos_canary.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(gnomeos_canary.time, "sleep", lambda _: None)

    def command(*args):
        state["commands"].append(args)
        if "org.gnome.Shell.Screenshot.Screenshot" in args:
            Path(args[-1]).write_bytes(b"png")
        return "GNOME Shell 49.0" if args[0] == "gnome-shell" else "gjs 1.86"

    monkeypatch.setattr(gnomeos_canary, "command", command)
    state["evidence"] = lambda: json.loads((tmp_path / "results/desktop-canary.json").read_text())
    state["probe"] = gnomeos_canary.probe
    return state


def test_probe_records_typed_value_and_screenshot(probe_env):
    probe_env["probe"]()
    evidence = probe_env["evidence"]()
    assert evidence["observed"] == evidence["expected"] and len(evidence["expected"]) == 16
    assert evidence["mutter_build_version"] == "49.0"
    assert any("org.gnome.Shell.Screenshot.Screenshot" in c for c in probe_env["commands"])
    assert FakeChild.last.terminated and FakeChild.last.waited
    assert FakePonytail.instances[-1].disconnected


def test_probe_writes_evidence_when_readback_never_matches(probe_env, monkeypatch):
    from tests.shared import gnomeos_canary
    monkeypatch.setattr(gnomeos_canary, "window_wait_diagnostics",
                        lambda child: {"screenshot": "saved"})
    probe_env["readback"] = lambda expected: expected[:-1]
    with pytest.raises(AssertionError, match="not observed over AT-SPI"):
        probe_env["probe"]()
    evidence = probe_env["evidence"]()
    assert evidence["observed"] == evidence["expected"][:-1]
    assert evidence["entry_found"] is True
    assert evidence["focused_after_typing"] is True
    assert evidence["after_typing_screenshot"] == "saved"
    assert not any("org.gnome.Shell.Screenshot.Screenshot" in c for c in probe_env["commands"])
    assert FakeChild.last.terminated and FakeChild.last.waited
    assert FakePonytail.instances[-1].disconnected


@pytest.mark.parametrize("fail_at", ["init", "wait"])
def test_probe_only_disconnects_after_connecting(probe_env, fail_at):
    FakePonytail.fail_at = fail_at
    with pytest.raises(RuntimeError):
        probe_env["probe"]()
    assert probe_env["evidence"]()["observed"] == ""
    assert FakeChild.last.terminated and FakeChild.last.waited
    assert all(not p.disconnected for p in FakePonytail.instances)


def test_probe_leaves_the_overview_with_escape_first(probe_env):
    # A session starts in the Activities overview, which covers the window.
    FakePonytail.window = "escape"
    probe_env["probe"]()
    evidence = probe_env["evidence"]()
    assert evidence["focus"] == "escape"
    assert evidence["observed"] == evidence["expected"]
    ponytail = FakePonytail.instances[-1]
    assert ponytail.control == [0xFF1B] and ponytail.clicks == []


def test_probe_focuses_an_unfocused_window_with_a_real_click(probe_env):
    # On Wayland the shell maps a background-launched window without focus;
    # Ponytail's waitFor() would time out on it. Escape alone isn't enough here.
    FakePonytail.window = "click"
    probe_env["probe"]()
    evidence = probe_env["evidence"]()
    assert evidence["focus"] == "click"
    assert evidence["observed"] == evidence["expected"]
    ponytail = FakePonytail.instances[-1]
    assert ponytail.windows == [7]  # clicked through the window connection
    (button, x, y), *_ = ponytail.clicks
    assert button == 1 and x == 240 and 37 < y < 157  # inside the entry, below any title bar


def test_probe_skips_the_click_when_the_window_already_has_focus(probe_env):
    probe_env["probe"]()
    assert probe_env["evidence"]()["focus"] == "already"
    assert FakePonytail.instances[-1].clicks == []


def test_probe_fails_with_diagnostics_when_focus_never_arrives(probe_env, monkeypatch):
    from tests.shared import gnomeos_canary
    FakePonytail.window = "never"
    monkeypatch.setattr(gnomeos_canary, "window_wait_diagnostics", lambda child: {"seen": "window"})
    with pytest.raises(AssertionError, match="never took keyboard focus"):
        probe_env["probe"]()
    evidence = probe_env["evidence"]()
    assert evidence["window_wait"] == {"seen": "window"}
    assert evidence["observed"] == ""
    assert FakePonytail.instances[-1].clicks  # it did try


def test_probe_fails_with_diagnostics_when_the_window_never_maps(probe_env, monkeypatch):
    from tests.shared import gnomeos_canary
    FakePonytail.window = "absent"
    monkeypatch.setattr(gnomeos_canary, "window_wait_diagnostics", lambda child: {"seen": "nothing"})
    with pytest.raises(ValueError, match="Timeout waiting for Window"):
        probe_env["probe"]()
    assert probe_env["evidence"]()["window_wait"] == {"seen": "nothing"}
    assert FakePonytail.instances[-1].windows == []


def test_probe_types_through_a_monitor_connection(probe_env):
    # dogtail types through connectMonitor(); keys sent through the window
    # connection never reached the entry on GNOME OS.
    probe_env["probe"]()
    evidence = probe_env["evidence"]()
    assert evidence["input"] == "keysym-monitor" and evidence["observed"] == evidence["expected"]
    assert FakePonytail.instances[-1].monitor_connected
