"""Custom step definitions for printing stack smoke checks."""
import random
import re
import time

from behave import step

from tests.shared.app_support import detached_launch_command

try:
    from qecore.common_steps import *  # noqa: F401,F403
except Exception:  # noqa: BLE001
    pass

# Reuse the same host-level runner as the other smoke host-state checks so
# commands execute inside the VM (via SSH) when behave runs in the runner
# container, rather than inside the container itself.
from system_health_steps import _run_host


_LISTENER_PORT = 19191
_LISTENER_READY = "/tmp/smoke-print-listener.ready"
_LISTENER_OUTPUT = "/tmp/smoke-print-capture.bin"
_LISTENER_SCRIPT = "/tmp/smoke_print_listener.py"


def _run_admin(cmd: str, timeout: int = 30):
    """Run a command as root with non-interactive sudo; fall back once."""
    for prefix in ("sudo -n", ""):
        full = f"{prefix} {cmd}".strip() if prefix else cmd
        out, rc, err = _run_host(full, timeout=timeout)
        if rc == 0:
            return out, rc, err
        combined = (out + " " + err).lower()
        if "unauthorized" not in combined and "permission denied" not in combined:
            break
    return out, rc, err


def _unmask_cups() -> None:
    """Unmask CUPS units that the CI VM masks to speed first-boot.

    The workflow masks units with both kernel command line ``systemd.mask=`` and
    ``/etc/systemd/system`` symlinks to ``/dev/null``.  ``systemctl unmask``
    removes the config symlinks, but ``daemon-reload`` re-runs
    ``systemd-debug-generator`` which recreates runtime masks under
    ``/run/systemd/generator.early``.  That directory has higher precedence than
    ``/etc/systemd/system``, so we copy the real unit files into
    ``/etc/systemd/system.control`` (the highest-priority load path) to shadow
    the regenerated masks.
    """
    units = ("cups.socket", "cups.service", "cups.path", "cups-browsed.service")
    _run_host("sudo -n mkdir -p /etc/systemd/system.control", timeout=10)
    for unit in units:
        # Remove any /etc or /run mask symlinks.
        _run_host(f"sudo -n systemctl unmask {unit} 2>/dev/null || true")
        # Copy the real unit into the highest-priority load path so it wins over
        # the runtime generator mask in /run/systemd/generator.early.
        _run_host(
            f"if [ -f /usr/lib/systemd/system/{unit} ]; then "
            f"sudo -n rm -f /etc/systemd/system.control/{unit} && "
            f"sudo -n cp /usr/lib/systemd/system/{unit} "
            f"/etc/systemd/system.control/{unit}; "
            f"fi",
            timeout=10,
        )
    _run_host(
        "if [ -f /etc/cups/cupsd.conf ] && ! grep -q 'MaxRequestSize' /etc/cups/cupsd.conf; then "
        "echo 'MaxRequestSize 0' | sudo -n tee -a /etc/cups/cupsd.conf >/dev/null; "
        "fi",
        timeout=10,
    )
    _run_host("sudo -n systemctl daemon-reload")


def _start_cups_socket() -> None:
    """Ensure cups.socket is started so the scheduler is reachable."""
    _unmask_cups()
    out, rc, err = _run_host("systemctl is-active cups.socket")
    if out == "active":
        return
    _run_admin("systemctl start cups.socket")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        out, rc, err = _run_host("systemctl is-active cups.socket")
        if out == "active":
            return
        time.sleep(0.5)
    raise AssertionError(f"cups.socket did not become active: {out} (rc={rc}, {err})")


def _ensure_scheduler_running() -> None:
    """Wait until lpstat -r reports the scheduler is running."""
    _start_cups_socket()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        out, rc, err = _run_host("lpstat -r")
        if rc == 0 and "scheduler is running" in out.lower():
            return
        time.sleep(1)
    raise AssertionError(f"CUPS scheduler is not running: {out} (rc={rc}, {err})")


def _parse_job_id(lp_output: str) -> str | None:
    """Extract the job id (e.g. 'printer-1') from lp stdout."""
    match = re.search(r"request id is (\S+)", lp_output)
    if match:
        return match.group(1)
    # Fallback: look for any 'name-N' token.
    match = re.search(r"(\S+-\d+)", lp_output)
    if match:
        return match.group(1)
    return None


def _start_socket_listener(port: int) -> None:
    """Start a local TCP listener that writes received bytes to a known file."""
    script = (
        "import socket, os, sys\n"
        f"PORT = {port}\n"
        f"OUT = '{_LISTENER_OUTPUT}'\n"
        f"READY = '{_LISTENER_READY}'\n"
        "# Clean up any stale marker/output\n"
        "import os\n"
        "for p in (OUT, READY):\n"
        "    try:\n"
        "        os.remove(p)\n"
        "    except FileNotFoundError:\n"
        "        pass\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "s.bind(('127.0.0.1', PORT))\n"
        "s.listen(1)\n"
        "open(READY, 'w').close()\n"
        "conn, _ = s.accept()\n"
        "data = b''\n"
        "while True:\n"
        "    chunk = conn.recv(4096)\n"
        "    if not chunk:\n"
        "        break\n"
        "    data += chunk\n"
        "open(OUT, 'wb').write(data)\n"
        "conn.close()\n"
        "s.close()\n"
        "try:\n"
        "    os.remove(READY)\n"
        "except FileNotFoundError:\n"
        "    pass\n"
    )
    _run_host(f"cat > {_LISTENER_SCRIPT} <<'PYEOF'\n{script}PYEOF")
    _run_host(detached_launch_command(f"python3 {_LISTENER_SCRIPT}"), timeout=10)
    # Wait for the ready marker.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        out, rc, _ = _run_host(f"test -f {_LISTENER_READY} && echo ready")
        if rc == 0 and out == "ready":
            return
        time.sleep(0.5)
    raise AssertionError("Print socket listener did not become ready")


def _stop_socket_listener() -> None:
    """Kill any leftover listener process and remove its artifacts."""
    _run_host(
        f"pkill -f {_LISTENER_SCRIPT} 2>/dev/null || true; "
        f"rm -f {_LISTENER_SCRIPT} {_LISTENER_READY} {_LISTENER_OUTPUT}",
        timeout=5,
    )


@step("cups.socket is enabled and active")
def cups_socket_is_enabled_and_active(context) -> None:  # noqa: ARG001
    # The CI VM masks CUPS units to shorten first-boot time.  Unmask before
    # asserting the stock enabled/active state.
    _unmask_cups()
    out, rc, err = _run_host("systemctl is-enabled cups.socket")
    assert rc == 0, f"systemctl is-enabled cups.socket failed: {err or out}"
    assert out in ("enabled", "static"), f"unexpected cups.socket enable state: {out}"
    _start_cups_socket()


@step("CUPS scheduler is running")
def cups_scheduler_is_running(context) -> None:  # noqa: ARG001
    _ensure_scheduler_running()


@step('virtual raw printer queue "{name}" accepts a test job and is removed')
def virtual_raw_printer_queue_accepts_job_and_removed(context, name: str) -> None:  # noqa: ARG001
    _ensure_scheduler_running()

    # The Bluefin testing image does not ship the CUPS file backend, so a
    # file:/ URI queue cannot spool.  Use a local TCP listener via the socket
    # backend instead; this gives us real spool data without needing hardware.
    port = _LISTENER_PORT + random.randint(0, 100)
    _start_socket_listener(port)

    try:
        out, rc, err = _run_admin(f"lpadmin -p {name} -E -v socket://127.0.0.1:{port} -m raw")
        assert rc == 0, f"lpadmin failed: {err or out}"

        test_payload = "/tmp/smoke-print-payload.txt"
        _run_host(f"printf 'smoke-print-payload\\n' > {test_payload}")
        out, rc, err = _run_host(f"lp -d {name} -o raw {test_payload}")
        assert rc == 0, f"lp failed: {err or out}"
        job_id = _parse_job_id(out)
        assert job_id, f"could not parse job id from lp output: {out}"

        # Wait for the listener to receive bytes.
        deadline = time.monotonic() + 20
        captured = ""
        while time.monotonic() < deadline:
            captured, rc, _ = _run_host(
                f"test -f {_LISTENER_OUTPUT} && stat -c%s {_LISTENER_OUTPUT}"
            )
            if rc == 0 and captured.isdigit() and int(captured) > 0:
                break
            time.sleep(1)
        else:
            raise AssertionError(
                f"Socket listener did not receive print data for job {job_id}"
            )
    finally:
        _run_admin(f"lpadmin -x {name} 2>/dev/null || true")
        _stop_socket_listener()
        _run_host("rm -f /tmp/smoke-print-payload.txt", timeout=5)
