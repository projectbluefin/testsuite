"""Unit tests for the startup-qualification lane (scripts/startup_lane.py, #1025)."""

from __future__ import annotations

import copy
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import startup_lane as lane

REPO = Path(__file__).parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "startup-qualification.yml"
COLLECTOR = REPO / "scripts" / "startup_lane_collect.sh"


@pytest.fixture(scope="module")
def inventory() -> dict:
    return lane.load_inventory()


def unit(name, active="active", sub="exited", result="success", load="loaded",
         condition="yes", cond_ts="12345", restarts="0", status="0"):
    return (
        f"Id={name}\nLoadState={load}\nActiveState={active}\nSubState={sub}\n"
        f"Result={result}\nConditionResult={condition}\n"
        f"ConditionTimestampMonotonic={cond_ts}\nExecMainStatus={status}\n"
        f"NRestarts={restarts}\nUnitFileState=enabled\n"
    )


BAZAAR_PREINSTALL = "[Flatpak Preinstall io.github.kolunmi.Bazaar]\nBranch=stable\nIsRuntime=false\n"


def evidence(system=None, user=None, paths=None, preinstall=None, remotes_declared=("flathub",),
             remotes=("flathub",), installed=("io.github.kolunmi.Bazaar\tstable\tflathub",),
             overrides=None) -> str:
    """Build collector output for a healthy Bluefin first boot, with overrides."""
    if system is None:
        system = [
            unit("NetworkManager-wait-online.service"),
            unit("brew-setup.service", active="inactive", sub="dead"),
            unit("flatpak-preinstall.service"),
        ]
    if user is None:
        user = [
            unit("podman-auto-update.service", active="inactive", sub="dead", cond_ts="0"),
            unit("podman-auto-update.timer", sub="waiting"),
        ]
    if paths is None:
        paths = ["yes /home/linuxbrew/.linuxbrew/bin/brew", "yes /etc/.linuxbrew"]
    if preinstall is None:
        preinstall = [("/usr/share/flatpak/preinstall.d/bazaar.preinstall", BAZAAR_PREINSTALL)]
    if overrides is None:
        overrides = [(
            "io.github.kolunmi.Bazaar",
            "/usr/share/ublue-os/flatpak-overrides/io.github.kolunmi.Bazaar",
            "[Context]\nfilesystems=host-etc\n",
            "[Context]\nshared=network;ipc;\nfilesystems=host-etc;xdg-download;\n",
        )]
    out = ["@@ is-system-running", "running"]
    out += ["@@ system-units", "\n".join(system)]
    out += ["@@ user-units", "\n".join(user)]
    out += ["@@ paths", *paths]
    for path, body in preinstall:
        out += [f"@@ preinstall-file {path}", body]
    out += ["@@ remotes-declared", *remotes_declared]
    out += ["@@ remotes", *remotes]
    out += ["@@ installed", *installed]
    out += ["@@ override-links"]
    for app, target, _, _ in overrides:
        out.append(f"/var/lib/flatpak/overrides/{app} {target} {target}")
    for app, _, file_body, perms in overrides:
        out += [f"@@ override-file {app}", file_body, f"@@ permissions {app}", perms]
    return "\n".join(out) + "\n"


def statuses(report) -> dict[str, str]:
    return {f.subject: f.status for f in report.findings}


# --- inventory and plan ------------------------------------------------------


def test_inventory_startup_lane_fields_are_valid(inventory):
    assert lane.validate(inventory) == []


def test_validate_rejects_missing_or_bad_startup_lane(inventory):
    broken = copy.deepcopy(inventory)
    del broken["brew-setup.service"]["startup_lane"]
    broken["firewalld.service"]["startup_lane"]["expect"] = "maybe"
    broken["flatpak-preinstall.service"]["startup_lane"]["deadline_s"] = 0
    broken["cups.service"]["startup_lane"] = {"expect": "completed"}
    broken["greenboot-healthcheck.service"]["startup_lane"]["expect"] = "completed"
    problems = "\n".join(lane.validate(broken))
    assert "brew-setup.service: startup_contract needs startup_lane" in problems
    assert "firewalld.service: expect must be one of" in problems
    assert "flatpak-preinstall.service: deadline_s must be a positive integer" in problems
    assert "cups.service: startup_lane only applies to startup_contract" in problems
    assert "greenboot-healthcheck.service: a deferred unit takes no other" in problems


def test_plan_never_masks_a_required_startup_unit(inventory):
    for profile in ("bluefin", "bluefin-lts", "aurora", "bazzite"):
        env = lane.plan(inventory, profile)
        masked = set(re.findall(r"systemd\.mask=(\S+)", env["KERNEL_MASKS"]))
        required = set(lane.required_units(inventory, profile))
        assert not masked & required, profile
        observed = set(env["SYSTEM_UNITS"].split()) | set(env["USER_UNITS"].split())
        assert observed == required, profile


def test_plan_masks_only_inapplicable_noise_and_deferred_units(inventory):
    masked = set(lane.lane_masks(inventory))
    for name, entry in inventory.items():
        deferred = bool(entry.get("startup_lane", {}).get("deferred"))
        expected = entry["category"] != "startup_contract" or deferred
        assert (name in masked) == expected, name
    assert "greenboot-healthcheck.service" in masked
    assert "flatpak-preinstall.service" not in masked


def test_plan_for_bluefin(inventory):
    env = lane.plan(inventory, "bluefin")
    assert env["SYSTEM_UNITS"].split() == [
        "NetworkManager-wait-online.service",
        "brew-setup.service",
        "flatpak-preinstall.service",
    ]
    assert env["USER_UNITS"].split() == ["podman-auto-update.service", "podman-auto-update.timer"]
    assert env["CHECKS"] == "flatpak"
    assert "/home/linuxbrew/.linuxbrew/bin/brew" in env["PRODUCES"].split()
    assert env["STARTUP_DEADLINE_S"] == "1800"
    assert env["NEGATIVE_CONTROL_UNIT"] in lane.required_units(inventory, "bluefin")


def test_negative_control_unit_is_required_on_every_profile(inventory):
    for profile in ("bluefin", "bluefin-lts", "aurora", "bazzite"):
        assert lane.NEGATIVE_CONTROL_UNIT in lane.required_units(inventory, profile), profile


def test_plan_rejects_unknown_profile(inventory):
    with pytest.raises(SystemExit):
        lane.plan(inventory, "nonesuch")


def test_bazzite_reports_greenboot_as_not_qualified(inventory):
    report = lane.evaluate(inventory, "bazzite", evidence(system=[
        unit("NetworkManager-wait-online.service"),
        unit("brew-setup.service", active="inactive", sub="dead"),
        unit("bazzite-hardware-setup.service"),
    ], user=[]), elapsed=100)
    got = statuses(report)
    assert got["greenboot-healthcheck.service"] == lane.DEFERRED
    assert got["greenboot-set-rollback-trigger.service"] == lane.DEFERRED
    assert report.verdict == lane.PASS


# --- unit judging ------------------------------------------------------------

COMPLETED = {"expect": "completed", "deadline_s": 300}


def props(text):
    return lane.parse_units(text)[text.split("\n", 1)[0].removeprefix("Id=")]


@pytest.mark.parametrize(
    "text, elapsed, want, why",
    [
        (unit("a.service"), 10, lane.PASS, "loaded/active/exited"),
        (unit("a.service", active="inactive", sub="dead"), 10, lane.PASS, "result=success"),
        (unit("a.service", active="inactive", sub="dead", cond_ts="0"), 10, lane.PENDING, "never started"),
        (unit("a.service", active="inactive", sub="dead", cond_ts="0"), 301, lane.FAIL, "deadline 300s"),
        (unit("a.service", active="activating", sub="start"), 10, lane.PENDING, "still starting"),
        (unit("a.service", active="activating", sub="start"), 400, lane.FAIL, "after 400s"),
        (unit("a.service", active="activating", sub="auto-restart", result="exit-code", restarts="1"), 10, lane.PENDING, "restarts=1"),
        (unit("a.service", active="failed", sub="failed", result="exit-code", status="1"), 10, lane.FAIL, "exit=1"),
        (unit("a.service", active="inactive", sub="dead", condition="no"), 10, lane.FAIL, "condition was not met"),
        (unit("a.service", load="masked", active="inactive", sub="dead"), 10, lane.FAIL, "masked"),
        (unit("a.service", load="not-found", active="inactive", sub="dead"), 10, lane.FAIL, "not shipped"),
    ],
)
def test_judge_completed_unit(text, elapsed, want, why):
    status, detail = lane.judge_unit("a.service", COMPLETED, props(text), elapsed)
    assert status == want
    assert why in detail


def test_judge_active_and_loaded_units():
    active = {"expect": "active", "deadline_s": 60}
    assert lane.judge_unit("t.timer", active, props(unit("t.timer", sub="waiting")), 5)[0] == lane.PASS
    assert lane.judge_unit("t.timer", active, props(unit("t.timer", active="inactive", sub="dead")), 5)[0] == lane.PENDING
    assert lane.judge_unit("t.timer", active, props(unit("t.timer", active="inactive", sub="dead")), 61)[0] == lane.FAIL
    loaded = {"expect": "loaded", "deadline_s": 60}
    idle = props(unit("p.service", active="inactive", sub="dead", cond_ts="0"))
    assert lane.judge_unit("p.service", loaded, idle, 5)[0] == lane.PASS
    failed = props(unit("p.service", active="failed", sub="failed", result="exit-code"))
    assert lane.judge_unit("p.service", loaded, failed, 5)[0] == lane.FAIL


def test_missing_unit_state_is_pending_then_fails():
    assert lane.judge_unit("a.service", COMPLETED, None, 10)[0] == lane.PENDING
    assert lane.judge_unit("a.service", COMPLETED, None, 300)[0] == lane.FAIL


# --- whole-run evaluation ----------------------------------------------------


def test_healthy_bluefin_first_boot_passes(inventory):
    report = lane.evaluate(inventory, "bluefin", evidence(), elapsed=600)
    got = statuses(report)
    assert report.verdict == lane.PASS, report.markdown("bluefin")
    assert got["flatpak io.github.kolunmi.Bazaar"] == lane.PASS
    assert got["remote flathub"] == lane.PASS
    assert got["override io.github.kolunmi.Bazaar"] == lane.PASS
    assert got["/etc/.linuxbrew"] == lane.PASS


def test_skipped_brew_setup_fails_even_though_systemd_says_success(inventory):
    system = [
        unit("NetworkManager-wait-online.service"),
        unit("brew-setup.service", active="inactive", sub="dead", condition="no"),
        unit("flatpak-preinstall.service"),
    ]
    report = lane.evaluate(inventory, "bluefin", evidence(system=system), elapsed=600)
    assert statuses(report)["brew-setup.service"] == lane.FAIL
    assert report.verdict == lane.FAIL


def test_missing_produced_path_fails(inventory):
    paths = ["no /home/linuxbrew/.linuxbrew/bin/brew", "yes /etc/.linuxbrew"]
    report = lane.evaluate(inventory, "bluefin", evidence(paths=paths), elapsed=600)
    assert statuses(report)["/home/linuxbrew/.linuxbrew/bin/brew"] == lane.FAIL


def test_flatpak_state_is_not_judged_until_preinstall_finishes(inventory):
    system = [
        unit("NetworkManager-wait-online.service"),
        unit("brew-setup.service", active="inactive", sub="dead"),
        unit("flatpak-preinstall.service", active="activating", sub="start"),
    ]
    report = lane.evaluate(inventory, "bluefin", evidence(system=system, installed=()), elapsed=120)
    assert report.verdict == lane.PENDING
    assert not any(f.subject.startswith("flatpak ") for f in report.findings)
    final = lane.evaluate(inventory, "bluefin", evidence(system=system), elapsed=120, final=True)
    assert statuses(final)["flatpak-preinstall.service"] == lane.FAIL


@pytest.mark.parametrize(
    "kwargs, subject, why",
    [
        ({"installed": ()}, "flatpak io.github.kolunmi.Bazaar", "not installed"),
        ({"installed": ("io.github.kolunmi.Bazaar\tbeta\tflathub",)}, "flatpak io.github.kolunmi.Bazaar", "asks for stable"),
        ({"installed": ("io.github.kolunmi.Bazaar\tstable\tsideload",)}, "flatpak io.github.kolunmi.Bazaar", "not configured"),
        ({"remotes": ()}, "remote flathub", "not configured"),
        ({"preinstall": []}, "flatpak preinstall.d", "declares no preinstalled refs"),
    ],
)
def test_flatpak_contract_failures(inventory, kwargs, subject, why):
    report = lane.evaluate(inventory, "bluefin", evidence(**kwargs), elapsed=600)
    finding = next(f for f in report.findings if f.subject == subject)
    assert finding.status == lane.FAIL
    assert why in finding.detail
    assert report.verdict == lane.FAIL


def test_etc_preinstall_drop_in_overrides_usr(inventory):
    preinstall = [
        ("/usr/share/flatpak/preinstall.d/bazaar.preinstall", BAZAAR_PREINSTALL),
        ("/usr/share/flatpak/preinstall.d/extra.preinstall", "[Flatpak Preinstall org.example.App]\n"),
        ("/etc/flatpak/preinstall.d/extra.preinstall", "[Flatpak Preinstall org.example.App]\nInstall=false\n"),
    ]
    sections = lane.parse_sections(evidence(preinstall=preinstall))
    assert lane.declared_preinstalls(sections) == {"io.github.kolunmi.Bazaar": "stable"}


def test_permission_override_not_in_effect_fails(inventory):
    overrides = [(
        "io.github.kolunmi.Bazaar",
        "/usr/share/ublue-os/flatpak-overrides/io.github.kolunmi.Bazaar",
        "[Context]\nfilesystems=host-etc;!home\n",
        "[Context]\nfilesystems=home;xdg-download;\n",
    )]
    report = lane.evaluate(inventory, "bluefin", evidence(overrides=overrides), elapsed=600)
    finding = next(f for f in report.findings if f.subject == "override io.github.kolunmi.Bazaar")
    assert finding.status == lane.FAIL
    assert "Context/filesystems=host-etc" in finding.detail
    assert "Context/filesystems=!home" in finding.detail


def test_dangling_override_link_fails(inventory):
    text = evidence().replace(
        "/var/lib/flatpak/overrides/io.github.kolunmi.Bazaar /usr/share/ublue-os/flatpak-overrides/io.github.kolunmi.Bazaar /usr/share/ublue-os/flatpak-overrides/io.github.kolunmi.Bazaar",
        "/var/lib/flatpak/overrides/io.github.kolunmi.Bazaar /usr/share/ublue-os/flatpak-overrides/io.github.kolunmi.Bazaar",
    )
    report = lane.evaluate(inventory, "bluefin", text, elapsed=600)
    assert statuses(report)["override io.github.kolunmi.Bazaar"] == lane.FAIL


def test_override_for_app_not_preinstalled_checks_link_only():
    assert lane.missing_permissions("", "") == ["override file is empty or missing"]
    assert lane.missing_permissions("[Environment]\nFOO=1\n", "[Environment]\nFOO=1\n") == []
    assert lane.missing_permissions("[Environment]\nFOO=1\n", "[Environment]\nFOO=2\n") == ["Environment/FOO=1"]
    assert lane.missing_permissions("[Context]\nshared=network\n", "not a keyfile") == [
        "unreadable keyfile (MissingSectionHeaderError)"
    ]


def test_parse_sections_keeps_arguments_and_bodies():
    text = "junk\n@@ a\n1\n2\n@@ b x y\n\n@@ c\n"
    assert lane.parse_sections(text) == [("a", "", "1\n2"), ("b", "x y", ""), ("c", "", "")]


# --- CLI ---------------------------------------------------------------------


def run_cli(tmp_path, text, *extra):
    path = tmp_path / "evidence.txt"
    path.write_text(text)
    report = tmp_path / "report.md"
    rc = lane.main(["evaluate", "--profile", "bluefin", "--evidence", str(path),
                    "--report", str(report), *extra])
    return rc, report.read_text()


def test_cli_exit_codes(tmp_path):
    assert run_cli(tmp_path, evidence(), "--elapsed", "600")[0] == 0
    rc, md = run_cli(tmp_path, "", "--elapsed", "10")
    assert rc == 3 and "pending" in md
    assert run_cli(tmp_path, "", "--elapsed", "10", "--final")[0] == 1


def test_cli_negative_control(tmp_path):
    system = [
        unit(lane.NEGATIVE_CONTROL_UNIT, active="failed", sub="failed", result="exit-code", status="1"),
        unit("brew-setup.service", active="inactive", sub="dead"),
        unit("flatpak-preinstall.service"),
    ]
    flag = ["--elapsed", "600", "--expect-failure", lane.NEGATIVE_CONTROL_UNIT]
    assert run_cli(tmp_path, evidence(system=system), *flag)[0] == 0
    # A green run is a broken negative control.
    assert run_cli(tmp_path, evidence(), *flag)[0] == 1
    # Still waiting: keep polling.
    assert run_cli(tmp_path, "", "--elapsed", "10", "--expect-failure", lane.NEGATIVE_CONTROL_UNIT)[0] == 3


def test_cli_rejects_invalid_inventory(tmp_path, inventory):
    bad = copy.deepcopy(inventory)
    del bad["brew-setup.service"]["startup_lane"]
    path = tmp_path / "inventory.yaml"
    path.write_text(yaml.safe_dump({"units": bad}))
    assert lane.main(["--inventory", str(path), "plan", "--profile", "bluefin"]) == 2


def test_cli_plan_prints_github_env_lines(capsys):
    assert lane.main(["plan", "--profile", "bluefin"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"^SYSTEM_UNITS=.*flatpak-preinstall\.service", out, re.MULTILINE)
    assert all("=" in line for line in out.splitlines())


# --- collector and workflow contract -----------------------------------------


def test_collector_is_valid_bash():
    subprocess.run(["bash", "-n", str(COLLECTOR)], check=True)


def test_collector_emits_every_section_the_evaluator_reads():
    script = COLLECTOR.read_text()
    source = Path(lane.__file__).read_text()
    read = set(re.findall(r'section\(sections, "([a-z-]+)"', source)) | {"preinstall-file"}
    emitted = set(re.findall(r'echo "@@ ([a-z-]+)', script))
    assert read <= emitted, read - emitted


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text()


def test_workflow_masks_come_only_from_the_plan(workflow_text):
    assert "systemd.mask=" not in workflow_text.replace("${KERNEL_MASKS}", "")
    assert "${KERNEL_MASKS}" in workflow_text


@pytest.mark.parametrize(
    "substitute",
    ["flatpak install", "flatpak-app-list", "brew install", "AutomaticLogin", "dnf install", "rpm-ostree install"],
)
def test_workflow_supplies_no_substitute_state(workflow_text, substitute):
    assert substitute not in workflow_text


def test_workflow_runs_the_negative_control_and_reruns_on_lane_changes(workflow_text):
    flow = yaml.safe_load(workflow_text)
    on = flow[True]  # PyYAML reads the bare `on:` key as boolean True
    assert set(on["pull_request"]["paths"]) >= {
        ".github/workflows/startup-qualification.yml",
        "scripts/startup_lane.py",
        "scripts/startup_lane_collect.sh",
        "startup_service_inventory.yaml",
    }
    assert '"broken"' in flow["jobs"]["startup"]["strategy"]["matrix"]["control"]
    assert "--expect-failure" in workflow_text
    assert "${NEGATIVE_CONTROL_UNIT}.d/99-negative-control.conf" in workflow_text
