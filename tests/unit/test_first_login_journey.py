"""First-boot journey (#1180): page sequencing, deadlines, cases and cleanup.

A fake guest stands in for the VM: it models GNOME Initial Setup 51.1's
pages, focus and Next button, the account it creates, the reboot and the
GDM greeter, and records every key the journey sends. Nothing boots here;
the hosted runs are the proof (desktop-first-login-cases.md).
"""
import json
from pathlib import Path

import pytest
import yaml

from scripts import first_login_journey as journey

ROOT = Path(__file__).parents[2]
WORKFLOW_TEXT = (ROOT / ".github/workflows/first-login-probe.yml").read_text()
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)
DISK_SCRIPT = (ROOT / "scripts/first_login_disk.sh").read_text()
UI_STATE = (ROOT / "scripts/first_login_ui_state.py").read_text()

UTAH_PAGES = ["language", "keyboard", "privacy", "timezone", "account", "password", "summary"]
NEXT = {"role": "push button", "name": "Next"}


class FakeGuest:
    """GNOME Initial Setup, the new account and the greeter, by key press."""

    def __init__(self, tmp_path, pages=UTAH_PAGES, loader=True, timezone_set=True,
                 autologin=False, handoff=True, keyboard_set=False):
        self.serial = tmp_path / "serial.log"
        self.serial.write_text("BdsDxe: loading Boot0001\nLinux version 6.18\n" if loader else
                               "BdsDxe: failed to load Boot0001\n")
        self.loader = loader
        self.pages = list(pages)
        self.index = 0
        self.timezone_set = timezone_set
        self.keyboard_set = keyboard_set  # utah: no system layout, none preselected
        self.searched = ""
        self.autologin = autologin
        self.handoff = handoff
        self.now = 0.0
        self.keys = []
        self.frames = []
        self.fields = ["", ""]
        self.field = None
        self.focus_ring = []
        self.focus_at = 0
        self.users = []
        self.password = None
        self.booted_after_setup = False
        self.greeter_prompt = False
        self.greeter_text = ""
        self.session = False
        self._enter_page()

    # clock -----------------------------------------------------------------
    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    # GIS model -------------------------------------------------------------
    @property
    def page(self):
        return self.pages[self.index] if self.index < len(self.pages) else None

    def _enter_page(self):
        page = self.page
        self.field = None
        if page == "account":
            self.focus_ring = [{"role": "text", "name": "Full Name"}, NEXT]
        elif page == "password":
            # GTK's password entries put a show-password toggle in Tab order.
            self.focus_ring = [NEXT, {"role": "password text", "name": "Password"},
                               {"role": "toggle button", "name": "Show Password"},
                               {"role": "password text", "name": "Confirm Password"}]
            self.fields = ["", ""]
        elif page == "keyboard" and not self.keyboard_set:
            self.focus_ring = [{"role": "text", "name": "Search keyboards and input methods"},
                               {"role": "list item", "name": "English (US)"}, NEXT]
        elif page == "timezone" and not self.timezone_set:
            self.focus_ring = [NEXT, {"role": "text", "name": "Search"}]
        elif page == "summary":
            self.focus_ring = [{"role": "push button", "name": "Start Using Bluefin"}]
        else:
            self.focus_ring = [NEXT]
        self.focus_at = 0

    def _next_sensitive(self):
        if self.page == "password":
            return self.fields[0] != "" and self.fields[0] == self.fields[1]
        if self.page == "timezone":
            return self.timezone_set
        if self.page == "keyboard":
            return self.keyboard_set
        return True

    def _focused(self):
        f = dict(self.focus_ring[self.focus_at])
        f["sensitive"] = self._next_sensitive() if f.get("name") == "Next" else True
        return f

    def ui_state(self, target):
        if target == "gis":
            if self.page is None:
                return {"ok": False, "error": "no gis process"}
            title = journey.PAGE_TITLES[self.page]
            return {"ok": True, "labels": [title, "some body text"],
                    "focused": self._focused(),
                    "buttons": [{"name": "Next", "sensitive": self._next_sensitive(),
                                 "focused": self._focused().get("name") == "Next"}],
                    "password_fields": 2 if self.page == "password" else 0}
        if not self.booted_after_setup:
            return {"ok": False, "error": "no greeter process"}
        state = {"ok": True, "labels": ["Firstboot"], "buttons": [],
                 "password_fields": 1 if self.greeter_prompt else 0,
                 "focused": ({"role": "password text", "name": "Password", "sensitive": True}
                             if self.greeter_prompt else
                             {"role": "push button", "name": "Firstboot", "sensitive": True})}
        return state

    def press(self, name, pause=0.25):
        self.keys.append(name)
        self.now += pause
        if self.booted_after_setup:
            if name == "ret" and not self.greeter_prompt:
                self.greeter_prompt = True
            elif name == "ret" and self.greeter_prompt:
                self.session = self.greeter_text == self.password
            return
        if self.page is None:
            return
        if name == "tab":
            self.focus_at = (self.focus_at + 1) % len(self.focus_ring)
        elif name == "down" and self.page == "timezone":
            pass
        elif name == "ret":
            f = self._focused()
            if self.page == "timezone" and f.get("role") == "text":
                self.timezone_set = True
            elif self.page == "keyboard" and f.get("role") == "list item":
                self.keyboard_set = self.searched == journey.KEYBOARD_SEARCH
            elif f.get("name") == "Next" and f["sensitive"]:
                self.index += 1
                self._enter_page()
            elif self.page == "summary":
                self.password = self.fields_final
                self.users = [["firstboot", "1000"]]
                self.index += 1

    def type_text(self, text):
        journey.key_names(text)  # same contract as the real guest
        self.keys.extend(["<typed>"] * len(text))
        if self.booted_after_setup:
            self.greeter_text = text
            return
        f = self._focused()
        if self.page == "keyboard" and f.get("role") == "text":
            self.searched = text
        if self.page == "password" and f.get("role") == "password text":
            self.fields[0 if f["name"] == "Password" else 1] = text
            self.fields_final = text

    def screendump(self, path):
        self.frames.append(Path(path).name)
        Path(path).write_bytes(b"P6 1 1 255\n\0\0\0")
        return b"frame"

    def wait_ssh(self, timeout):
        return self.loader

    def initial_setup(self):
        return {"running": self.page is not None, "regular_users": []}

    def ssh(self, command, timeout=20):
        if "systemctl reboot" in command:
            self.booted_after_setup = True
            self.session = self.autologin
            return 0, ""
        if "/etc/passwd" in command:
            return 0, "\n".join(" ".join(u) for u in self.users)
        if command.startswith("id -nG"):
            return 0, "firstboot wheel"
        if "loginctl" in command:
            active = self.session or (self.handoff and self.users and not self.booted_after_setup)
            return 0, ("Id=3\nUser=1000\nType=wayland\nState=active\nClass=user\n\n"
                       if active else "Id=1\nUser=60578\nType=wayland\nState=active\nClass=greeter\n\n")
        if "gnome-initial-setup-done" in command:
            return 0, "yes" if self.users else ""
        if "journalctl" in command:
            return 0, "journal line\n"
        return 0, ""


def run_case(tmp_path, case, guest):
    out = tmp_path / "out"
    rc = journey.run(case, out, "mon.sock", guest.serial, "key", guest=guest)
    return rc, json.loads((out / "verdict.json").read_text()), out


# --- sequencing ---------------------------------------------------------------

def test_happy_path_walks_every_page_in_order_and_logs_in(tmp_path):
    guest = FakeGuest(tmp_path)
    rc, verdict, _ = run_case(tmp_path, "happy", guest)
    assert rc == 0, verdict
    assert verdict["pages"] == UTAH_PAGES
    assert verdict["checkpoint"] == "desktop"
    assert verdict["account"] == {"name": "firstboot", "uid": 1000, "groups": ["firstboot", "wheel"]}
    assert verdict["failure"] is None and verdict["passed"]


def test_network_page_is_optional_but_handled_when_shown(tmp_path):
    pages = ["language", "keyboard", "network"] + UTAH_PAGES[2:]
    rc, verdict, _ = run_case(tmp_path, "happy", FakeGuest(tmp_path, pages=pages))
    assert rc == 0, verdict
    assert verdict["pages"] == pages


def test_keyboard_layout_is_chosen_when_none_is_preselected(tmp_path):
    guest = FakeGuest(tmp_path, keyboard_set=False)
    rc, verdict, _ = run_case(tmp_path, "happy", guest)
    assert rc == 0, verdict
    assert guest.keyboard_set


def test_a_preselected_keyboard_layout_is_kept(tmp_path):
    guest = FakeGuest(tmp_path, keyboard_set=True)
    rc, verdict, _ = run_case(tmp_path, "happy", guest)
    assert rc == 0, verdict
    assert guest.searched == ""


def test_focus_failure_names_what_tab_reached(tmp_path):
    guest = FakeGuest(tmp_path)
    with pytest.raises(journey.JourneyFailure) as failure:
        journey.focus(guest, "gis", lambda f: False, "nothing")
    assert "push button:Next" in failure.value.reason


def test_timezone_without_a_location_is_searched_by_keyboard(tmp_path):
    guest = FakeGuest(tmp_path, timezone_set=False)
    rc, verdict, _ = run_case(tmp_path, "happy", guest)
    assert rc == 0, verdict


def test_a_missing_required_page_is_named(tmp_path):
    pages = [p for p in UTAH_PAGES if p != "privacy"]
    rc, verdict, _ = run_case(tmp_path, "happy", FakeGuest(tmp_path, pages=pages))
    assert rc == 1
    assert verdict["failure"] == "required-page-missing"
    assert "privacy" in verdict["reason"]


def test_missing_page_case_passes_only_on_that_failure(tmp_path):
    pages = [p for p in UTAH_PAGES if p != "privacy"]
    rc, verdict, _ = run_case(tmp_path, "missing-page", FakeGuest(tmp_path, pages=pages))
    assert rc == 0 and verdict["passed"]
    rc, verdict, _ = run_case(tmp_path, "missing-page", FakeGuest(tmp_path))
    assert rc == 1 and not verdict["passed"]  # the journey passed: not the named failure


def test_next_expected_rejects_going_back_and_unknown_pages():
    with pytest.raises(journey.JourneyFailure) as back:
        journey.next_expected(3, "keyboard")
    assert back.value.kind == "unrecognized-screen"
    with pytest.raises(journey.JourneyFailure):
        journey.next_expected(0, "software")
    assert journey.next_expected(2, "privacy") == 3  # network skipped: optional


def test_two_titles_at_once_is_a_transition_not_a_checkpoint():
    state = {"ok": True, "labels": ["Typing", "Privacy"]}
    assert journey.page_from_state(state) is None
    assert journey.page_from_state({"ok": True, "labels": ["Privacy"]}) == "privacy"
    assert journey.page_from_state({"ok": False}) is None


# --- deadlines ----------------------------------------------------------------

def test_an_unrecognised_screen_fails_at_its_deadline(tmp_path):
    guest = FakeGuest(tmp_path)
    guest.ui_state = lambda target: {"ok": True, "labels": ["Something Else"]}
    rc, verdict, _ = run_case(tmp_path, "happy", guest)
    assert rc == 1
    assert verdict["failure"] == "unrecognized-screen"
    assert guest.now >= journey.PAGE_TIMEOUT


def test_focus_gives_up_after_a_bounded_number_of_tabs(tmp_path):
    guest = FakeGuest(tmp_path)
    with pytest.raises(journey.JourneyFailure):
        journey.focus(guest, "gis", lambda f: False, "nothing")
    assert guest.keys.count("tab") == journey.MAX_TABS


# --- cases ----------------------------------------------------------------------

def test_wrong_password_case_fails_at_authentication(tmp_path):
    rc, verdict, _ = run_case(tmp_path, "wrong-password", FakeGuest(tmp_path))
    assert rc == 0 and verdict["passed"], verdict
    assert verdict["failure"] == "authentication"
    assert verdict["checkpoint"] == "handoff"


def test_no_loader_case_fails_at_the_handoff(tmp_path):
    rc, verdict, _ = run_case(tmp_path, "no-loader", FakeGuest(tmp_path, loader=False))
    assert rc == 0 and verdict["passed"]
    assert verdict["failure"] == "loader-handoff"


def test_auto_login_after_reboot_is_an_authentication_failure(tmp_path):
    rc, verdict, _ = run_case(tmp_path, "happy", FakeGuest(tmp_path, autologin=True))
    assert rc == 1
    assert verdict["failure"] == "authentication"


def test_no_handoff_session_fails(tmp_path):
    rc, verdict, _ = run_case(tmp_path, "happy", FakeGuest(tmp_path, handoff=False))
    assert rc == 1 and verdict["failure"] == "handoff"


def test_unknown_case_is_a_usage_error(tmp_path):
    assert journey.run("other", tmp_path, "s", "l", "k", guest=FakeGuest(tmp_path)) == 2


# --- credentials and cleanup --------------------------------------------------

def test_password_is_per_run_and_typeable():
    a, b = journey.make_password(), journey.make_password()
    assert a != b and len(a) == 24
    assert len(journey.key_names(a)) == 24
    with pytest.raises(ValueError):
        journey.key_names("pass word!")


def test_no_frame_is_kept_from_private_pages(tmp_path):
    guest = FakeGuest(tmp_path)
    run_case(tmp_path, "happy", guest)
    for private in journey.PRIVATE_PAGES:
        assert not any(private in f for f in guest.frames)
    assert any("frame-page" in f for f in guest.frames)


def test_password_never_reaches_the_verdict_or_stdout(tmp_path, capsys):
    guest = FakeGuest(tmp_path)
    run_case(tmp_path, "happy", guest)
    secret = guest.password
    assert secret
    assert secret not in capsys.readouterr().out
    assert not journey.scan_for(secret, tmp_path / "out")


def test_a_leaked_password_deletes_the_evidence_and_fails(tmp_path):
    guest = FakeGuest(tmp_path)
    leaked = {}

    def leaky(path):
        if guest.password and not leaked:
            Path(path).write_text(guest.password)
            leaked["yes"] = True
        return b"frame"

    original = guest.screendump
    guest.screendump = lambda path: leaky(path) if "desktop" in str(path) else original(path)
    rc, verdict, out = run_case(tmp_path, "happy", guest)
    assert rc == 1
    assert verdict["failure"] == "credential-exposure"
    assert [p.name for p in out.iterdir()] == ["verdict.json"]


def test_evidence_is_collected_on_failure_too(tmp_path):
    rc, verdict, out = run_case(tmp_path, "no-loader", FakeGuest(tmp_path, loader=False))
    assert (out / "serial.log").exists()
    assert (out / "guest-journal.txt").exists()


def test_parse_sessions_reads_key_value_blocks_in_any_order():
    text = "Type=wayland\nUser=1000\nClass=user\nState=active\nId=3\n\nId=1\nUser=60578\n"
    sessions = journey.parse_sessions(text)
    assert sessions[0]["User"] == "1000" and sessions[1]["Id"] == "1"


# --- guest reader, disk fixtures and workflow ---------------------------------

def test_ui_reader_only_reads():
    code = "\n".join(l for l in UI_STATE.splitlines() if not l.lstrip().startswith("#"))
    for forbidden in ("get_text(", "set_text", "do_action", "grab_focus", "generate_keyboard_event"):
        assert forbidden not in code
    assert "os.setuid(uid)" in code  # drops to the target session's own user


def test_disk_fixtures_break_only_what_their_case_needs():
    assert 'case "$FIXTURE" in none|no-loader|missing-page)' in DISK_SCRIPT
    assert 'sudo rm -rf "$ESPMNT/EFI"' in DISK_SCRIPT
    assert "skip=software;privacy" in DISK_SCRIPT
    # The loader is checked before the no-loader fixture removes it.
    assert DISK_SCRIPT.index("EFI/BOOT/BOOTX64.EFI$") < DISK_SCRIPT.index('sudo rm -rf "$ESPMNT/EFI"')


def test_each_case_gets_its_own_job_and_fresh_disk():
    job = WORKFLOW["jobs"]["journey"]
    assert job["strategy"]["fail-fast"] is False
    assert "fromJSON(inputs.cases" in job["strategy"]["matrix"]["case"]
    for case in ("happy", "wrong-password", "missing-page", "no-loader"):
        assert case in job["strategy"]["matrix"]["case"]
    steps = {s.get("name"): s for s in job["steps"]}
    assert "first_login_journey.py" in steps["Drive the first-boot journey"]["run"]
    assert "${FIXTURE}" in steps["Prepare the first-boot disk"]["run"]
    assert "first-boot-journey-${{ matrix.case }}" in WORKFLOW_TEXT


def test_journey_files_trigger_the_pull_request_run():
    paths = WORKFLOW[True]["pull_request"]["paths"]
    for path in ("scripts/first_login_journey.py", "scripts/first_login_ui_state.py",
                 "tests/unit/test_first_login_journey.py"):
        assert path in paths
