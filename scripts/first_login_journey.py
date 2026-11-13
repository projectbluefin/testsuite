#!/usr/bin/env python3
"""First-boot journey (#1180): drive GNOME Initial Setup, then log in at GDM.

Builds on the probe (scripts/first_login_probe.py, #1179). The VM was booted
by the workflow through OVMF and the disk's own loader, from a disk prepared
by scripts/first_login_disk.sh for one CASE. Input is QEMU monitor key presses
only. Before each action the driver waits, with a deadline, for that page's
checkpoint, read from the guest by scripts/first_login_ui_state.py over the
per-run root SSH key (accessibility names and states only, never entry text).

The page order is the admission record's (docs/skills/test-authoring/
uefi-boot/references/desktop-first-login.md, utah:testing):
language, keyboard, network, privacy, timezone, account, password, summary.
Network hides itself when the guest is already online, so it may be absent;
every other page is required.

CASE (each on its own fresh disk and variable store):
  happy           the whole journey passes
  wrong-password  the journey up to the greeter, then a wrong password: must
                  fail with "authentication"
  missing-page    the disk's vendor policy skips privacy: must fail with
                  "required-page-missing"
  no-loader       the disk's ESP has no loader: must fail with "loader-handoff"

A controlled-failure case passes only when the run fails with exactly its
named failure. Writes OUTDIR/verdict.json.

The account password is generated per run in this process's memory. It is
never printed, written to a file or passed in a process argument, no frame is
kept from the account, password or summary pages or of the greeter's password
prompt, and before exiting every retained file is scanned for it; a hit
deletes the evidence and fails the run ("credential-exposure").

Usage: first_login_journey.py CASE OUTDIR MONITOR_SOCKET SERIAL_LOG SSH_KEY
"""
import json
import secrets
import shutil
import string
import subprocess
import sys
import time
from pathlib import Path

try:
    import first_login_probe as probe  # run as a script from scripts/
except ImportError:  # imported as scripts.first_login_journey (unit tests)
    from scripts import first_login_probe as probe

CASES = {
    "happy": "",
    "wrong-password": "authentication",
    "missing-page": "required-page-missing",
    "no-loader": "loader-handoff",
}

# Header-bar titles of GNOME Initial Setup 51.1's pages (gis_page_set_title).
PAGE_TITLES = {
    "language": "Welcome",
    "keyboard": "Typing",
    "network": "Network",
    "privacy": "Privacy",
    "timezone": "Time Zone",
    "account": "About You",
    "password": "Password",
    "summary": "Setup Complete",
}
EXPECTED_PAGES = ("language", "keyboard", "network", "privacy", "timezone",
                  "account", "password", "summary")
OPTIONAL_PAGES = frozenset({"network"})
# No frame is retained from these pages: they show account details or the
# password field (desktop-first-login-cases.md, "Credentials and retained
# evidence").
PRIVATE_PAGES = frozenset({"account", "password", "summary"})

FULL_NAME = "Firstboot"  # artificial; GIS derives the username from it
# The image sets no system keyboard layout, so GIS 51.1 preselects none and
# Next stays insensitive until one is chosen. Its chooser filters by word
# prefix and sorts by name, so this puts "English (US)" first.
KEYBOARD_SEARCH = "english us"
ROW_ROLES = ("list item", "row", "table row")
TIMEZONE_SEARCH = "London"
PAGE_TIMEOUT = 120
MAX_TABS = 25

UI_STATE = Path(__file__).with_name("first_login_ui_state.py")

KEYS = {c: c for c in string.ascii_lowercase + string.digits}
KEYS.update({c: f"shift-{c.lower()}" for c in string.ascii_uppercase})
KEYS[" "] = "spc"


class JourneyFailure(Exception):
    """A checkpoint failed; ``kind`` is the named failure."""

    def __init__(self, kind, reason):
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


def make_password(length=24):
    """A per-run password: letters and digits only, so every character has a
    monitor key name, with at least one of each class for pwquality."""
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)):
            return pw


def key_names(text):
    """QEMU monitor key names for ``text``; raises on a character with none."""
    try:
        return [KEYS[c] for c in text]
    except KeyError as exc:
        raise ValueError("character has no monitor key name") from exc


def page_from_state(state):
    """The page whose header title is showing, or None (transition/unknown).

    Two titles at once is a slide between pages: not yet a checkpoint.
    """
    if not state or not state.get("ok"):
        return None
    labels = set(state.get("labels", []))
    seen = [page for page, title in PAGE_TITLES.items() if title in labels]
    return seen[0] if len(seen) == 1 else None


def next_expected(current_index, page):
    """Decide what seeing ``page`` means when EXPECTED_PAGES[current_index]
    is the next page due.

    Returns ``page``'s index. Raises JourneyFailure when a required page was
    skipped or the page is out of order.
    """
    if page not in EXPECTED_PAGES:
        raise JourneyFailure("unrecognized-screen", f"unknown page {page!r}")
    target = EXPECTED_PAGES.index(page)
    if target < current_index:
        raise JourneyFailure("unrecognized-screen",
                             f"went back to {page} after {EXPECTED_PAGES[current_index]}")
    skipped = [p for p in EXPECTED_PAGES[current_index:target] if p not in OPTIONAL_PAGES]
    if skipped:
        raise JourneyFailure("required-page-missing",
                             f"required page {skipped[0]} never appeared; saw {page}")
    return target


class Guest:
    """The VM's three host-side channels: monitor, serial log and root SSH."""

    def __init__(self, sock, serial, key, clock=time.monotonic, sleep=time.sleep):
        self.sock, self.serial, self.key = sock, serial, key
        self.clock, self.sleep = clock, sleep

    def press(self, name, pause=0.25):
        probe.monitor(self.sock, f"sendkey {name}")
        self.sleep(pause)

    def type_text(self, text):
        # Key names only reach the monitor socket; nothing is logged.
        for name in key_names(text):
            self.press(name, pause=0.08)

    def ssh(self, command, timeout=20):
        return probe.ssh(self.key, command, timeout)

    def ui_state(self, target):
        argv = ["ssh", "-i", str(self.key), "-p", "2222", "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=5", "root@127.0.0.1", f"python3 - {target}"]
        try:
            done = subprocess.run(argv, input=UI_STATE.read_text(), capture_output=True,
                                  text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "ui state read timed out"}
        try:
            return json.loads(done.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            return {"ok": False, "error": f"no ui state (ssh exit {done.returncode})"}

    def screendump(self, path):
        return probe.screendump(self.sock, path)

    def wait_ssh(self, timeout):
        return probe.wait_for_ssh(self.key, timeout, clock=self.clock, sleep=self.sleep)

    def initial_setup(self):
        return probe.initial_setup_running(self.key)


def wait_for(predicate, timeout, guest, interval=3):
    """Poll ``predicate()`` until it returns a truthy value or the deadline."""
    deadline = guest.clock() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if guest.clock() >= deadline:
            return None
        guest.sleep(interval)


def focus(guest, target, wanted, what):
    """Press Tab until the focused widget satisfies ``wanted(focused)``.

    On failure the reason lists what Tab did reach (widget roles and names,
    never entry text), so the next run knows where focus went.
    """
    reached = []
    for _ in range(MAX_TABS):
        state = guest.ui_state(target)
        focused = (state or {}).get("focused") or {}
        if state.get("ok") and wanted(focused):
            return focused
        stop = f"{focused.get('role', '-')}:{focused.get('name', '')}"[:60]
        if stop not in reached:
            reached.append(stop)
        guest.press("tab", pause=0.5)
    raise JourneyFailure("unrecognized-screen",
                         f"could not focus {what}; Tab reached {reached[:12]}")


TEXT_ROLES = ("text", "entry", "password text")


def is_text(f):
    return f.get("role") in TEXT_ROLES


def is_password_field(f):
    return f.get("role") == "password text" or (
        f.get("role") in TEXT_ROLES and "assword" in f.get("name", ""))


def is_button(name):
    return lambda f: f.get("role") in ("push button", "button") and f.get("name") == name


def press_next(guest, page):
    """Focus GIS's Next button (it must be sensitive) and activate it."""
    focused = focus(guest, "gis", is_button("Next"), f"Next on {page}")
    if not focused.get("sensitive"):
        raise JourneyFailure("unrecognized-screen", f"Next is not available on {page}")
    guest.press("ret", pause=1)


def button_sensitive(state, name):
    return any(b["name"] == name and b["sensitive"] for b in state.get("buttons", []))


def act_on_page(guest, page, password):
    if page in ("language", "privacy"):
        press_next(guest, page)
    elif page == "keyboard":
        if not button_sensitive(guest.ui_state("gis"), "Next"):
            focus(guest, "gis", is_text, "the keyboard search")
            guest.type_text(KEYBOARD_SEARCH)
            guest.sleep(2)
            focus(guest, "gis", lambda f: f.get("role") in ROW_ROLES, "the first layout row")
            guest.press("ret", pause=2)
        press_next(guest, page)
    elif page == "network":
        state = guest.ui_state("gis")
        if button_sensitive(state, "Next"):
            press_next(guest, page)
        else:
            focus(guest, "gis", is_button("Skip"), "Skip on network")
            guest.press("ret", pause=1)
    elif page == "timezone":
        if not button_sensitive(guest.ui_state("gis"), "Next"):
            focus(guest, "gis", is_text, "the time zone search")
            guest.type_text(TIMEZONE_SEARCH)
            guest.sleep(3)
            guest.press("down", pause=0.5)
            guest.press("ret", pause=2)
        press_next(guest, page)
    elif page == "account":
        # GIS focuses Full Name when the page is shown (gis_account_page_local_shown).
        focus(guest, "gis", is_text, "the Full Name field")
        guest.type_text(FULL_NAME)
        guest.sleep(2)  # GIS fills the username from the full name
        press_next(guest, page)
    elif page == "password":
        focus(guest, "gis", is_password_field, "the password field")
        guest.type_text(password)
        guest.press("tab", pause=0.5)
        focused = (guest.ui_state("gis").get("focused") or {})
        if not is_password_field(focused):
            raise JourneyFailure("unrecognized-screen", "no password confirmation field")
        guest.type_text(password)
        guest.sleep(1)
        press_next(guest, page)
    elif page == "summary":
        focused = (guest.ui_state("gis").get("focused") or {})
        if focused.get("role") not in ("push button", "button"):
            raise JourneyFailure("unrecognized-screen", "summary start button not focused")
        guest.press("ret", pause=1)


def drive_initial_setup(guest, out, password, verdict, page_timeout=PAGE_TIMEOUT):
    """Walk the admission record's pages in order; return the pages seen."""
    seen = []
    index = 0
    last = None
    while True:
        def arrived():
            page = page_from_state(guest.ui_state("gis"))
            return page if page and page != last else None

        page = wait_for(arrived, page_timeout, guest)
        if page is None:
            state = guest.ui_state("gis")
            raise JourneyFailure("unrecognized-screen",
                                 f"no recognised page within {page_timeout}s after "
                                 f"{last or 'start'}; showing {state.get('labels', [])[:12]}")
        index = next_expected(index, page) + 1
        seen.append(page)
        verdict["pages"] = list(seen)
        if page not in PRIVATE_PAGES:
            guest.screendump(out / f"frame-page-{len(seen):02d}-{page}.ppm")
        act_on_page(guest, page, password)
        last = page
        if page == "summary":
            return seen


def regular_users(guest):
    _, users = guest.ssh("awk -F: '$3>=1000 && $3<60000 {print $1\" \"$3}' /etc/passwd")
    return [u.split() for u in users.splitlines() if len(u.split()) == 2]


def parse_sessions(text):
    """Sessions from ``loginctl show-session`` output: blank-line separated
    blocks of Key=value lines (the property order is the bus's, not ours)."""
    sessions, current = [], {}
    for line in text.splitlines() + [""]:
        key, sep, value = line.partition("=")
        if sep:
            current[key.strip()] = value.strip()
        elif current:
            sessions.append(current)
            current = {}
    return sessions


def user_session(guest, uid):
    """An active graphical user session of ``uid``, as loginctl reports it."""
    _, out = guest.ssh(
        "for s in $(loginctl list-sessions --no-legend | awk '{print $1}'); do "
        "loginctl show-session \"$s\" -p Id -p User -p Type -p State -p Class; echo; done")
    for s in parse_sessions(out):
        if (s.get("User") == str(uid) and s.get("Class") == "user"
                and s.get("Type") in ("wayland", "x11")
                and s.get("State") in ("active", "online")):
            return f"session {s.get('Id')} {s.get('Type')} {s.get('State')}"
    return ""


def login_at_greeter(guest, out, password, timeout=300):
    """Select the user at GDM's greeter and submit ``password``."""
    def prompt():
        state = guest.ui_state("greeter")
        if not state.get("ok"):
            return None
        if state.get("password_fields"):
            return state
        guest.press("ret", pause=2)  # select the focused user in the list
        return None

    if not wait_for(prompt, timeout, guest, interval=5):
        raise JourneyFailure("authentication", "the greeter never showed a password prompt")
    focus(guest, "greeter", is_password_field, "the greeter password")
    guest.type_text(password)
    guest.press("ret", pause=2)


def reboot(guest, timeout=420):
    guest.ssh("systemctl reboot", timeout=10)
    guest.sleep(20)
    if not guest.wait_ssh(timeout):
        raise JourneyFailure("unrecognized-screen", "root SSH did not come back after reboot")


def collect(guest, out):
    # Every boot: the journey reboots once.
    rc, journal = guest.ssh("journalctl --no-pager -o short-iso", timeout=90)
    (out / "guest-journal.txt").write_text(journal if rc == 0 else "")
    try:
        shutil.copy(guest.serial, out / "serial.log")
    except OSError:
        pass


def scan_for(secret, out):
    """Files under ``out`` that contain ``secret``, raw or as monitor keys."""
    needles = [secret.encode(), " ".join(key_names(secret)).encode()]
    hits = []
    for path in sorted(out.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            if any(n in data for n in needles):
                hits.append(path.name)
    return hits


def journey(case, out, guest, password, verdict):
    # 1. Firmware hands off to the disk's loader, then a kernel.
    loader = probe.wait_for_serial(guest.serial, probe.LOADER_PATTERNS, 300,
                                   clock=guest.clock, sleep=guest.sleep)
    kernel = probe.wait_for_serial(guest.serial, (probe.KERNEL_PATTERN,), 300,
                                   clock=guest.clock, sleep=guest.sleep)
    verdict.update(loader_line=loader, kernel_line=kernel)
    guest.screendump(out / "frame-boot.ppm")
    if not kernel:
        raise JourneyFailure("loader-handoff", "no kernel boot on serial: the firmware "
                             "did not hand off to a loader")
    verdict["checkpoint"] = "loader"

    # 2. GNOME Initial Setup is the session and the disk has no regular user.
    if not guest.wait_ssh(420):
        raise JourneyFailure("unrecognized-screen", "root SSH never came up")

    def gis_running():
        evidence = guest.initial_setup()
        return evidence if evidence["running"] else None

    evidence = wait_for(gis_running, 420, guest, interval=5)
    if not evidence:
        raise JourneyFailure("unrecognized-screen", "GNOME Initial Setup never started")
    if evidence["regular_users"]:
        raise JourneyFailure("unrecognized-screen", "the disk already has a regular user")
    verdict["checkpoint"] = "initial-setup"

    # 3. The admission record's pages, in order, by keyboard.
    drive_initial_setup(guest, out, password, verdict)
    verdict["checkpoint"] = "pages"

    # 4. The account exists, and GIS hands off to its session.
    users = wait_for(lambda: regular_users(guest), 120, guest)
    if not users or len(users) != 1:
        raise JourneyFailure("account", f"expected one new regular user, found {users}")
    name, uid = users[0][0], int(users[0][1])
    _, groups = guest.ssh(f"id -nG {name}")
    verdict["account"] = {"name": name, "uid": uid, "groups": groups.split()}
    if uid < 1000 or "wheel" not in groups.split():
        raise JourneyFailure("account", f"{name} uid {uid} groups {groups!r}: expected "
                             "uid >= 1000 and wheel (GIS makes the first user an administrator)")
    handoff = wait_for(lambda: user_session(guest, uid), 180, guest, interval=5)
    if not handoff:
        raise JourneyFailure("handoff", "GIS did not hand off to a session for the new user")
    marker = wait_for(lambda: guest.ssh(
        f"test -f ~{name}/.config/gnome-initial-setup-done && echo yes")[1] == "yes",
        120, guest, interval=5)
    if not marker:
        raise JourneyFailure("handoff", "no gnome-initial-setup-done marker for the new user")
    verdict["handoff_session"] = handoff
    guest.screendump(out / "frame-handoff-desktop.ppm")
    verdict["checkpoint"] = "handoff"

    # 5. Reboot to GDM's greeter and log in with the password.
    reboot(guest)
    if user_session(guest, uid):
        raise JourneyFailure("authentication", "a session exists before any login (auto-login?)")
    wait_for(lambda: guest.ui_state("greeter").get("ok"), 300, guest, interval=5)
    guest.screendump(out / "frame-greeter.ppm")
    secret = password if case != "wrong-password" else make_password()
    login_at_greeter(guest, out, secret)
    session = wait_for(lambda: user_session(guest, uid), 120, guest, interval=5)
    if not session:
        _, pam = guest.ssh("journalctl -b --no-pager | grep -c 'gdm-password.*authentication failure' || true")
        verdict["greeter_auth_failures"] = pam
        raise JourneyFailure("authentication",
                             "the greeter did not open a session for the new user")
    verdict["login_session"] = session
    guest.sleep(10)
    guest.screendump(out / "frame-desktop.ppm")
    verdict["checkpoint"] = "desktop"


def run(case, outdir, sock, serial, key, guest=None):
    if case not in CASES:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    guest = guest or Guest(sock, serial, key)
    expected = CASES[case]
    verdict = {"case": case, "expected_failure": expected or None, "checkpoint": "start"}
    password = make_password()
    try:
        journey(case, out, guest, password, verdict)
        verdict["failure"] = None
    except JourneyFailure as failure:
        verdict.update(failure=failure.kind, reason=failure.reason)
    finally:
        collect(guest, out)
    hits = scan_for(password, out)
    password = None
    if hits:
        for path in out.iterdir():
            if path.is_file():
                path.unlink()
        verdict.update(failure="credential-exposure",
                       reason=f"the password appeared in {len(hits)} retained file(s); evidence deleted")
    verdict["passed"] = verdict["failure"] == (expected or None)
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print("first-boot journey: " + json.dumps(verdict), flush=True)
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(run(*sys.argv[1:6]))
