#!/usr/bin/env python3
"""Answer polkit password prompts for one process, from inside the guest.

The technique is ChairLift's own (projectbluefin/chairlift
test/e2e/docker_system_integration.py, ``AuthenticationAgent``): a real
``pkttyagent --process <pid>`` on a private PTY, given a throwaway password.
No polkit rule is installed and nothing is authorized without a prompt.

It runs with the guest's python3 (standard library only), started over SSH as
a transient user unit: the runner container has neither the guest's polkit nor
its system bus. The password is read from a file in the guest, so it never
reaches the container, a command line or the behave log, and the transcript is
written with it replaced.
"""

from __future__ import annotations

import argparse
import os
import pty
import re
import select
import signal
import sys
import termios
import time

REDACTED = b"[throwaway password]"
REGISTER_TIMEOUT = 20
# pkttyagent prints the prompt and only then turns echo off with TCSAFLUSH,
# which drops anything already typed. Wait this long for echo to go off.
ECHO_OFF_WAIT = 2.0
PASSWORD_PROMPT = re.compile(rb"password:\s*", re.IGNORECASE)
# pkttyagent asks which administrator to authenticate as when there are several.
IDENTITY_PROMPT = re.compile(rb"Choose identity to authenticate as \(\d+-\d+\):\s*")
IDENTITY_LINE = re.compile(rb"^\s*(\d+)\.\s+(.*?)\s*$", re.MULTILINE)


class AgentError(Exception):
    """The agent could not start, or exited while it was still needed."""


def pick_identity(listing: bytes, user: bytes) -> bytes:
    """The number pkttyagent listed for ``user``, else the first identity."""
    for number, label in IDENTITY_LINE.findall(listing):
        if user and re.search(rb"(^|[\s(])" + re.escape(user) + rb"($|[\s)])", label):
            return number
    return b"1"


class Agent:
    """One pkttyagent bound to ``subject`` (the GUI's pid) on a private PTY."""

    def __init__(self, subject: int, password: bytes, user: bytes, status: str, transcript: str):
        self.subject = subject
        self.password = password
        self.user = user
        self.status_path = status
        self.transcript_path = transcript
        self.transcript = b""
        self.pending = b""
        self.prompts = 0
        self.pid = 0
        self.terminal = -1

    def note(self, line: str) -> None:
        with open(self.status_path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def save(self) -> None:
        """Write what the agent printed, never the password it was given."""
        with open(self.transcript_path, "wb") as handle:
            handle.write(self.transcript.replace(self.password, REDACTED))

    def start(self) -> None:
        ready, notify = os.pipe()
        os.set_inheritable(notify, True)
        self.pid, self.terminal = pty.fork()
        if self.pid == 0:
            os.close(ready)
            try:
                os.execvp("pkttyagent", ["pkttyagent", "--process", str(self.subject), "--notify-fd", str(notify)])
            except OSError:
                os.write(notify, b"!")  # anything but end-of-file means "never started"
                os._exit(127)
        os.close(notify)
        try:
            if not select.select([ready], [], [], REGISTER_TIMEOUT)[0]:
                raise AgentError(f"pkttyagent did not register within {REGISTER_TIMEOUT}s")
            # pkttyagent closes the descriptor once it has registered.
            if os.read(ready, 1) != b"":
                raise AgentError("pkttyagent could not be started (is polkit installed?)")
        finally:
            os.close(ready)
        if os.waitpid(self.pid, os.WNOHANG)[0]:
            self.pid = 0
            raise AgentError("pkttyagent exited instead of registering")
        self.note("registered")

    def pump(self, timeout: float = 0.2) -> bool:
        """Read what the agent printed; answer a prompt if one is complete."""
        if not select.select([self.terminal], [], [], timeout)[0]:
            return False
        try:
            data = os.read(self.terminal, 4096)
        except OSError:  # EIO: the agent closed its side of the PTY
            data = b""
        if not data:
            raise AgentError("pkttyagent exited before it was stopped")
        self.transcript += data
        self.pending += data
        choice = IDENTITY_PROMPT.search(self.pending)
        if choice is not None:
            number = pick_identity(self.pending[:choice.start()], self.user)
            self.pending = self.pending[choice.end():]
            os.write(self.terminal, number + b"\n")
            self.note(f"identity {number.decode()}")
            return True
        prompt = PASSWORD_PROMPT.search(self.pending)
        if prompt is None:
            return False
        self.pending = self.pending[prompt.end():]
        self.prompts += 1
        if not self.wait_for_echo_off():
            self.note(f"echo still on after {ECHO_OFF_WAIT}s, answering anyway")
        os.write(self.terminal, self.password + b"\n")
        self.note(f"answered {self.prompts}")
        self.save()
        return True

    def wait_for_echo_off(self) -> bool:
        """True once pkttyagent has switched echo off, so the answer is not flushed.

        On Linux the PTY master reports the terminal settings of its slave side.
        """
        deadline = time.monotonic() + ECHO_OFF_WAIT
        while True:
            try:
                if not termios.tcgetattr(self.terminal)[3] & termios.ECHO:
                    return True
            except termios.error:
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.005)

    def stop(self) -> None:
        self.save()
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            os.waitpid(self.pid, 0)
            self.pid = 0
        if self.terminal >= 0:
            os.close(self.terminal)
            self.terminal = -1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--process", type=int, required=True, help="pid of the GUI that will call pkexec")
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--status", required=True, help="progress lines: registered, answered N, stopped, error")
    parser.add_argument("--transcript", required=True, help="what pkttyagent printed, password replaced")
    parser.add_argument("--stop-file", required=True, help="the agent exits once this file exists")
    parser.add_argument("--timeout", type=float, default=300, help="seconds before the agent stops by itself")
    args = parser.parse_args(argv)

    open(args.status, "w", encoding="utf-8").close()
    with open(args.password_file, "rb") as handle:
        password = handle.read().strip()
    user = os.environ.get("USER", "").encode()
    agent = Agent(args.process, password, user, args.status, args.transcript)
    if not password:
        agent.note("error: the password file is empty")
        return 2

    stopping = []
    try:
        agent.start()
        # Only now: a handler installed before the fork would be inherited by
        # the child until it execs, and would swallow the SIGTERM stop() sends.
        signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
        deadline = time.monotonic() + args.timeout
        while not stopping and time.monotonic() < deadline and not os.path.exists(args.stop_file):
            agent.pump()
        agent.note(f"stopped prompts={agent.prompts}")
        return 0
    except AgentError as error:
        agent.note(f"error: {error}")
        return 1
    finally:
        agent.stop()


if __name__ == "__main__":
    sys.exit(main())
