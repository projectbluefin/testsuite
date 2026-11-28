"""Unit tests for tests/chairlift/polkit_tty_agent.py.

A stand-in ``pkttyagent`` is put first on PATH and run on a real PTY, so the
fork, registration and prompt handling are exercised without polkit. These are
logic checks, not proof that polkit accepts the agent in a GNOME session.
"""
import os
import signal
import sys
import textwrap

import pytest

from tests.chairlift import polkit_tty_agent as agent

PASSWORD = "0123456789abcdef0123456789abcdef"

# Prints what the real agent prints, reads answers from its terminal, records
# them, then asks the agent under test to stop by creating the stop file.
FAKE_AGENT = textwrap.dedent(
    """\
    #!{python}
    import os, sys, termios, time
    args = sys.argv[1:]
    assert args[0] == "--process" and args[2] == "--notify-fd", args
    mode = os.environ["FAKE_AGENT_MODE"]
    os.close(int(args[3]))
    if mode == "exit":
        sys.exit(3)
    if mode == "idle":
        time.sleep(30)
    def ask(prompt):
        # As polkitagenttextlistener.c on_request does: print the prompt, then
        # turn echo off with TCSAFLUSH, which drops anything typed in between.
        sys.stdout.write(prompt)
        sys.stdout.flush()
        if mode == "echo":
            return sys.stdin.readline()
        time.sleep(0.1)
        attrs = termios.tcgetattr(0)
        saved = list(attrs)
        attrs[3] &= ~(termios.ECHO | termios.ECHOE | termios.ECHOK | termios.ECHONL)
        termios.tcsetattr(0, termios.TCSAFLUSH, attrs)
        line = sys.stdin.readline()
        termios.tcsetattr(0, termios.TCSAFLUSH, saved)
        return line
    got = open(os.environ["FAKE_AGENT_GOT"], "w")
    got.write("process=" + args[1] + "\\n")
    sys.stdout.write("==== AUTHENTICATING FOR io.projectbluefin.chairlift.ublue.auto-updates-disable ====\\n")
    sys.stdout.write("Authenticating as: Bluefin Test (bluefin-test)\\n")
    got.write("first=" + ask("Password: "))
    sys.stdout.write("==== AUTHENTICATION COMPLETE ====\\n")
    sys.stdout.write("Multiple identities can be used for authentication:\\n")
    sys.stdout.write(" 1.  root\\n 2.  Bluefin Test (bluefin-test)\\n")
    sys.stdout.write("Choose identity to authenticate as (1-2): ")
    sys.stdout.flush()
    got.write("identity=" + sys.stdin.readline())
    got.write("second=" + ask("Password: "))
    got.close()
    sys.stdout.write("==== AUTHENTICATION COMPLETE ====\\n")
    sys.stdout.flush()
    open(os.environ["FAKE_AGENT_STOP"], "w").close()
    time.sleep(30)
    """
)


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Run the agent's main() against the stand-in pkttyagent in ``mode``."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "pkttyagent"
    fake.write_text(FAKE_AGENT.format(python=sys.executable), encoding="utf-8")
    fake.chmod(0o755)
    password_file = tmp_path / "password"
    password_file.write_text(PASSWORD + "\n", encoding="utf-8")
    paths = {
        "status": tmp_path / "status",
        "transcript": tmp_path / "transcript",
        "stop": tmp_path / "stop",
        "got": tmp_path / "got",
        "password": password_file,
        "bindir": bindir,
    }
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("USER", "bluefin-test")
    monkeypatch.setenv("FAKE_AGENT_GOT", str(paths["got"]))
    monkeypatch.setenv("FAKE_AGENT_STOP", str(paths["stop"]))
    handler = signal.getsignal(signal.SIGTERM)

    def _run(mode="prompt", timeout="20"):
        monkeypatch.setenv("FAKE_AGENT_MODE", mode)
        return agent.main([
            "--process", "4242", "--password-file", str(password_file),
            "--status", str(paths["status"]), "--transcript", str(paths["transcript"]),
            "--stop-file", str(paths["stop"]), "--timeout", timeout,
        ])

    yield _run, paths
    signal.signal(signal.SIGTERM, handler)


@pytest.mark.parametrize("listing,user,expected", [
    (b" 1.  root\n 2.  Bluefin Test (bluefin-test)\n", b"bluefin-test", b"2"),
    (b" 1.  bluefin-test\n 2.  root\n", b"bluefin-test", b"1"),
    (b" 1.  root\n 2.  bluefin-tester\n", b"bluefin-test", b"1"),
    (b" 1.  root\n 2.  other\n", b"", b"1"),
    (b"", b"bluefin-test", b"1"),
])
def test_pick_identity(listing, user, expected):
    assert agent.pick_identity(listing, user) == expected


def test_agent_answers_every_prompt_and_never_writes_the_password(run):
    _run, paths = run
    assert _run() == 0
    assert paths["status"].read_text().splitlines() == [
        "registered", "answered 1", "identity 2", "answered 2", "stopped prompts=2",
    ]
    assert paths["got"].read_text().splitlines() == [
        "process=4242", f"first={PASSWORD}", "identity=2", f"second={PASSWORD}",
    ]
    transcript = paths["transcript"].read_bytes()
    assert PASSWORD.encode() not in transcript
    assert b"AUTHENTICATING FOR io.projectbluefin.chairlift.ublue.auto-updates-disable" in transcript
    # The answer waited for echo to go off, so it was neither echoed nor flushed.
    assert agent.REDACTED not in transcript


def test_agent_answers_anyway_when_echo_stays_on_and_redacts_the_echo(run, monkeypatch):
    _run, paths = run
    monkeypatch.setattr(agent, "ECHO_OFF_WAIT", 0.05)
    assert _run(mode="echo") == 0
    assert paths["status"].read_text().splitlines() == [
        "registered", "echo still on after 0.05s, answering anyway", "answered 1",
        "identity 2", "echo still on after 0.05s, answering anyway", "answered 2", "stopped prompts=2",
    ]
    transcript = paths["transcript"].read_bytes()
    assert PASSWORD.encode() not in transcript
    # The PTY echoed what was typed into it, so the replacement must be there.
    assert agent.REDACTED in transcript


def test_agent_stops_by_itself_at_its_timeout(run):
    _run, paths = run
    assert _run(mode="idle", timeout="0.5") == 0
    assert paths["status"].read_text().splitlines() == ["registered", "stopped prompts=0"]
    assert paths["transcript"].read_bytes() == b""


def test_agent_reports_a_pkttyagent_that_exits(run):
    _run, paths = run
    assert _run(mode="exit") == 1
    lines = paths["status"].read_text().splitlines()
    assert lines[-1] in {
        "error: pkttyagent exited instead of registering",
        "error: pkttyagent exited before it was stopped",
    }
    assert not any(line.startswith("stopped") for line in lines)


def test_agent_reports_a_missing_pkttyagent(run, monkeypatch):
    _run, paths = run
    (paths["bindir"] / "pkttyagent").unlink()
    monkeypatch.setenv("PATH", str(paths["bindir"]))
    assert _run() == 1
    assert paths["status"].read_text().splitlines() == [
        "error: pkttyagent could not be started (is polkit installed?)",
    ]


def test_agent_refuses_an_empty_password_file(run):
    _run, paths = run
    paths["password"].write_text("\n", encoding="utf-8")
    assert _run() == 2
    assert paths["status"].read_text().splitlines() == ["error: the password file is empty"]
    assert not paths["transcript"].exists()


def test_registration_times_out(run, monkeypatch):
    _run, paths = run
    monkeypatch.setattr(agent, "REGISTER_TIMEOUT", 0)
    monkeypatch.setattr(agent.select, "select", lambda *a, **kw: ([], [], []))
    assert _run(mode="idle") == 1
    assert paths["status"].read_text().splitlines() == ["error: pkttyagent did not register within 0s"]
