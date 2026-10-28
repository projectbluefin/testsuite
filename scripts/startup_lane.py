#!/usr/bin/env python3
"""Startup-qualification lane: judge shipped first-boot services (testsuite#1025).

The fast e2e lane masks first-boot services and supplies its own Flatpaks, so
it says nothing about the image's startup contract. The startup lane boots the
candidate with every ``startup_contract`` unit from
``startup_service_inventory.yaml`` left as shipped, then uses this script to:

``plan``
    Print ``KEY=value`` lines for ``$GITHUB_ENV``: the kernel ``systemd.mask=``
    arguments (vm_inapplicable, ci_noise and deferred units only), the units to
    observe, the paths they must produce, the extra checks, and the overall
    deadline.

``evaluate``
    Parse the output of ``scripts/startup_lane_collect.sh`` and judge each
    required unit and, once flatpak-preinstall has finished, the system
    Flatpak state the image itself declares (preinstall.d, remotes.d and
    tmpfiles.d permission overrides). Exit 0 when everything passed, 1 when
    something failed, 3 while something is still pending inside its deadline.
    ``--final`` turns anything still pending into a failure.
    ``--expect-failure UNIT`` inverts the verdict for the negative control:
    exit 0 only when the run failed and UNIT is among the failures.

Usage:
    python3 scripts/startup_lane.py plan --profile bluefin >> "$GITHUB_ENV"
    python3 scripts/startup_lane.py evaluate --profile bluefin \\
        --evidence evidence.txt --elapsed 412 [--final] [--report out.md]
"""

from __future__ import annotations

import argparse
import configparser
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
INVENTORY = REPO / "startup_service_inventory.yaml"

PASS, FAIL, PENDING, DEFERRED = "pass", "fail", "pending", "not qualified"
EXIT = {PASS: 0, FAIL: 1, PENDING: 3}

# Broken on purpose by the negative-control job: every profile requires it and
# no other required unit hard-depends on it, so one failure is expected.
NEGATIVE_CONTROL_UNIT = "NetworkManager-wait-online.service"

EXPECTS = {"completed", "active", "loaded"}
SCOPES = {"system", "user"}
CHECKS = {"flatpak"}
# Who adds the system Flatpak remote: the image (remotes.d) or the installer.
FLATPAK_REMOTES = {"image", "installer"}
# Unit states that are still moving toward a result.
TRANSIENT = {"activating", "deactivating", "reloading", "refreshing"}


@dataclass
class Finding:
    subject: str
    status: str
    detail: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, subject: str, status: str, detail: str) -> None:
        self.findings.append(Finding(subject, status, detail))

    @property
    def verdict(self) -> str:
        statuses = {f.status for f in self.findings}
        if FAIL in statuses:
            return FAIL
        if PENDING in statuses:
            return PENDING
        return PASS

    def failed(self) -> set[str]:
        return {f.subject for f in self.findings if f.status == FAIL}

    def markdown(self, profile: str) -> str:
        lines = [
            f"### Startup qualification: `{profile}` — {self.verdict}",
            "",
            "| Check | Result | Detail |",
            "|---|---|---|",
        ]
        for f in self.findings:
            detail = f.detail.replace("|", "\\|")
            lines.append(f"| `{f.subject}` | {f.status} | {detail} |")
        return "\n".join(lines) + "\n"


# --- inventory ---------------------------------------------------------------


def load_inventory(path: Path = INVENTORY) -> dict:
    return yaml.safe_load(path.read_text())["units"]


def applies(entry: dict, profile: str) -> bool:
    profiles = entry.get("profiles", [])
    return "all" in profiles or profile in profiles


def lane_entry(entry: dict) -> dict:
    return entry.get("startup_lane") or {}


def required_units(inventory: dict, profile: str) -> dict[str, dict]:
    """startup_contract units this profile ships and the lane must run."""
    return {
        unit: lane_entry(entry)
        for unit, entry in inventory.items()
        if entry["category"] == "startup_contract"
        and applies(entry, profile)
        and not lane_entry(entry).get("deferred")
    }


def deferred_units(inventory: dict, profile: str) -> dict[str, str]:
    return {
        unit: lane_entry(entry)["deferred"]
        for unit, entry in inventory.items()
        if entry["category"] == "startup_contract"
        and applies(entry, profile)
        and lane_entry(entry).get("deferred")
    }


def lane_masks(inventory: dict) -> list[str]:
    """Units the startup lane still masks: never a required startup path."""
    return sorted(
        unit
        for unit, entry in inventory.items()
        if entry["category"] != "startup_contract" or lane_entry(entry).get("deferred")
    )


def validate(inventory: dict) -> list[str]:
    """Return problems with the startup_lane fields; empty when well-formed."""
    problems = []
    for unit, entry in inventory.items():
        lane = lane_entry(entry)
        if entry["category"] != "startup_contract":
            if lane:
                problems.append(f"{unit}: startup_lane only applies to startup_contract")
            continue
        if not lane:
            problems.append(f"{unit}: startup_contract needs startup_lane")
            continue
        if lane.get("deferred"):
            if set(lane) != {"deferred"}:
                problems.append(f"{unit}: a deferred unit takes no other startup_lane keys")
            continue
        if lane.get("expect") not in EXPECTS:
            problems.append(f"{unit}: expect must be one of {sorted(EXPECTS)}")
        if lane.get("scope", "system") not in SCOPES:
            problems.append(f"{unit}: scope must be one of {sorted(SCOPES)}")
        deadline = lane.get("deadline_s")
        if not isinstance(deadline, int) or deadline <= 0:
            problems.append(f"{unit}: deadline_s must be a positive integer")
        if not set(lane.get("checks", [])) <= CHECKS:
            problems.append(f"{unit}: unknown checks {lane.get('checks')}")
        if any(not str(p).startswith("/") for p in lane.get("produces", [])):
            problems.append(f"{unit}: produces must be absolute paths")
        if "flatpak_remote" in lane:
            if lane["flatpak_remote"] not in FLATPAK_REMOTES:
                problems.append(f"{unit}: flatpak_remote must be one of {sorted(FLATPAK_REMOTES)}")
            if "flatpak" not in lane.get("checks", []):
                problems.append(f"{unit}: flatpak_remote needs checks: [flatpak]")
    return problems


def known_profiles(inventory: dict) -> set[str]:
    return {p for entry in inventory.values() for p in entry.get("profiles", [])} - {"all"}


def plan(inventory: dict, profile: str) -> dict[str, str]:
    if profile not in known_profiles(inventory):
        raise SystemExit(f"unknown profile {profile!r}; inventory knows {sorted(known_profiles(inventory))}")
    required = required_units(inventory, profile)
    by_scope = {
        scope: sorted(u for u, lane in required.items() if lane.get("scope", "system") == scope)
        for scope in SCOPES
    }
    return {
        "KERNEL_MASKS": " ".join(f"systemd.mask={u}" for u in lane_masks(inventory)),
        "SYSTEM_UNITS": " ".join(by_scope["system"]),
        "USER_UNITS": " ".join(by_scope["user"]),
        "PRODUCES": " ".join(p for lane in required.values() for p in lane.get("produces", [])),
        "CHECKS": " ".join(sorted({c for lane in required.values() for c in lane.get("checks", [])})),
        "STARTUP_DEADLINE_S": str(max(lane["deadline_s"] for lane in required.values())),
        "NEGATIVE_CONTROL_UNIT": NEGATIVE_CONTROL_UNIT,
    }


# --- evidence parsing --------------------------------------------------------


def parse_sections(text: str) -> list[tuple[str, str, str]]:
    """Split collector output into (section, argument, body) triples."""
    sections: list[tuple[str, str, str]] = []
    name = arg = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("@@ "):
            if name is not None:
                sections.append((name, arg, "\n".join(body)))
            name, _, arg = line[3:].partition(" ")
            body = []
        elif name is not None:
            body.append(line)
    if name is not None:
        sections.append((name, arg, "\n".join(body)))
    return sections


def section(sections, name: str, arg: str = "") -> str | None:
    for n, a, body in sections:
        if n == name and a == arg:
            return body
    return None


def parse_units(text: str | None) -> dict[str, dict[str, str]]:
    """Parse `systemctl show` blocks (blank-line separated) keyed by Id."""
    units: dict[str, dict[str, str]] = {}
    for block in (text or "").split("\n\n"):
        props = dict(
            line.split("=", 1) for line in block.splitlines() if "=" in line
        )
        if props.get("Id"):
            units[props["Id"]] = props
    return units


def parse_keyfile(text: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False, delimiters=("=",))
    parser.optionxform = str
    parser.read_string(text)
    return parser


def declared_preinstalls(sections) -> dict[str, str]:
    """Refs the image asks flatpak-preinstall to install: {name: branch}."""
    by_basename: dict[str, str] = {}
    for name, arg, body in sections:
        if name == "preinstall-file":
            # Later sections are /etc, which overrides /usr by file name.
            by_basename[Path(arg).name] = body
    wanted: dict[str, str] = {}
    for body in by_basename.values():
        keyfile = parse_keyfile(body)
        for group in keyfile.sections():
            if not group.startswith("Flatpak Preinstall "):
                continue
            ref = group.removeprefix("Flatpak Preinstall ").strip()
            install = keyfile.get(group, "Install", fallback="true").strip().lower()
            if install == "false":
                wanted.pop(ref, None)
            else:
                wanted[ref] = keyfile.get(group, "Branch", fallback="").strip()
    return wanted


def lines(text: str | None) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


# --- judging -----------------------------------------------------------------


def judge_unit(unit: str, lane: dict, props: dict[str, str] | None, elapsed: int) -> tuple[str, str]:
    deadline = lane["deadline_s"]
    expect = lane["expect"]
    if props is None:
        return PENDING if elapsed < deadline else FAIL, "no state collected"
    load = props.get("LoadState", "")
    active = props.get("ActiveState", "")
    sub = props.get("SubState", "")
    result = props.get("Result", "")
    state = f"{load}/{active}/{sub} result={result}"
    if load == "masked":
        return FAIL, f"masked ({state}); the startup lane must run it as shipped"
    if load != "loaded":
        return FAIL, f"not shipped or not loadable ({state})"
    if active == "failed" or (result not in ("", "success") and sub != "auto-restart"):
        return FAIL, f"failed ({state}, exit={props.get('ExecMainStatus', '?')})"
    if expect == "loaded":
        return PASS, state

    def pending(why: str) -> tuple[str, str]:
        if elapsed < deadline:
            return PENDING, why
        return FAIL, f"{why} after {elapsed}s (deadline {deadline}s)"

    if active in TRANSIENT or sub == "auto-restart":
        return pending(f"still starting ({state}, restarts={props.get('NRestarts', '0')})")
    if expect == "active":
        return (PASS, state) if active == "active" else pending(f"not active ({state})")
    # expect == "completed"
    if props.get("ConditionTimestampMonotonic", "0") in ("", "0"):
        return pending(f"never started ({state})")
    if props.get("ConditionResult") == "no":
        return FAIL, f"skipped: a start condition was not met ({state})"
    return PASS, f"{state} restarts={props.get('NRestarts', '0')}"


def judge_flatpak(report: Report, sections, remote_from: str = "image") -> None:
    wanted = declared_preinstalls(sections)
    if not wanted:
        report.add("flatpak preinstall.d", FAIL, "image declares no preinstalled refs")
    configured = set(lines(section(sections, "remotes")))
    declared = lines(section(sections, "remotes-declared"))
    # bootc install to-disk runs no installer, so an installer-provided remote
    # is absent and the refs that need it cannot be qualified on this path.
    installer_gap = remote_from == "installer" and not configured and not declared
    if installer_gap:
        report.add(
            "flatpak remote",
            DEFERRED,
            "image ships no remotes.d file and installers add the system remote; "
            "bootc install to-disk runs no installer",
        )
    for remote in declared:
        status = PASS if remote in configured else FAIL
        report.add(f"remote {remote}", status, "declared in remotes.d; configured" if status == PASS else "declared in remotes.d but not configured")

    installed: dict[str, tuple[str, str]] = {}
    for line in lines(section(sections, "installed")):
        cols = line.split("\t") if "\t" in line else line.split()
        if len(cols) >= 3:
            installed[cols[0]] = (cols[1], cols[2])
    for ref, branch in sorted(wanted.items()):
        if ref not in installed:
            why = "declared in preinstall.d but not installed system-wide"
            if installer_gap:
                report.add(f"flatpak {ref}", DEFERRED, why + "; needs the installer-provided remote")
                continue
            if not configured:
                why += "; no system remote is configured, so flatpak preinstall has nothing to install it from"
            report.add(f"flatpak {ref}", FAIL, why)
            continue
        have_branch, origin = installed[ref]
        if branch and have_branch != branch:
            report.add(f"flatpak {ref}", FAIL, f"branch {have_branch}, preinstall.d asks for {branch}")
        elif origin not in configured:
            report.add(f"flatpak {ref}", FAIL, f"origin remote {origin!r} is not configured")
        else:
            report.add(f"flatpak {ref}", PASS, f"installed from {origin} ({have_branch})")

    for line in lines(section(sections, "override-links")):
        parts = line.split()
        link, target = parts[0], parts[1]
        resolved = parts[2] if len(parts) > 2 else ""
        app = Path(link).name
        if resolved != target:
            report.add(f"override {app}", FAIL, f"{link} resolves to {resolved or 'nothing'}, tmpfiles.d says {target}")
            continue
        if app not in installed:
            report.add(f"override {app}", PASS, "link in place; app not preinstalled, permissions not checked")
            continue
        missing = missing_permissions(
            section(sections, "override-file", app) or "",
            section(sections, "permissions", app) or "",
        )
        if missing:
            report.add(f"override {app}", FAIL, "not in effect: " + ", ".join(missing))
        else:
            report.add(f"override {app}", PASS, "shipped permission override in effect")


def missing_permissions(override: str, effective: str) -> list[str]:
    """Override entries that the app's effective permissions do not reflect."""
    try:
        want, have = parse_keyfile(override), parse_keyfile(effective)
    except configparser.Error as exc:
        return [f"unreadable keyfile ({exc.__class__.__name__})"]
    if not want.sections():
        return ["override file is empty or missing"]
    missing = []
    for group in want.sections():
        for key, value in want.items(group):
            got = have.get(group, key, fallback=None)
            if ";" in value or group == "Context":
                tokens = {t for t in got.split(";") if t} if got else set()
                for token in (t for t in value.split(";") if t):
                    present = token.lstrip("!") in tokens
                    if present == token.startswith("!"):
                        missing.append(f"{group}/{key}={token}")
            elif got != value:
                missing.append(f"{group}/{key}={value}")
    return missing


def evaluate(inventory: dict, profile: str, evidence: str, elapsed: int, final: bool = False) -> Report:
    sections = parse_sections(evidence)
    units = parse_units(section(sections, "system-units"))
    units.update(parse_units(section(sections, "user-units")))
    paths = {
        path: state
        for state, _, path in (ln.partition(" ") for ln in lines(section(sections, "paths")))
    }
    report = Report()
    flatpak_lane = None
    for unit, lane in sorted(required_units(inventory, profile).items()):
        status, detail = judge_unit(unit, lane, units.get(unit), elapsed)
        if final and status == PENDING:
            status, detail = FAIL, f"{detail}; lane deadline reached"
        report.add(unit, status, detail)
        if status != PASS:
            continue
        for path in lane.get("produces", []):
            ok = paths.get(path) == "yes"
            report.add(path, PASS if ok else FAIL, f"{'present' if ok else 'missing'} after {unit}")
        if "flatpak" in lane.get("checks", []):
            flatpak_lane = lane
    if flatpak_lane is not None:
        judge_flatpak(report, sections, flatpak_lane.get("flatpak_remote", "image"))
    for unit, why in sorted(deferred_units(inventory, profile).items()):
        report.add(unit, DEFERRED, why)
    return report


# --- CLI ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    sub = parser.add_subparsers(dest="command", required=True)
    p_plan = sub.add_parser("plan")
    p_plan.add_argument("--profile", required=True)
    p_eval = sub.add_parser("evaluate")
    p_eval.add_argument("--profile", required=True)
    p_eval.add_argument("--evidence", type=Path, required=True)
    p_eval.add_argument("--elapsed", type=int, required=True)
    p_eval.add_argument("--final", action="store_true")
    p_eval.add_argument("--report", type=Path)
    p_eval.add_argument("--expect-failure", metavar="UNIT")
    args = parser.parse_args(argv)

    inventory = load_inventory(args.inventory)
    problems = validate(inventory)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2

    if args.command == "plan":
        for key, value in plan(inventory, args.profile).items():
            print(f"{key}={value}")
        return 0

    report = evaluate(
        inventory, args.profile, args.evidence.read_text(errors="replace"), args.elapsed, args.final
    )
    text = report.markdown(args.profile)
    print(text)
    if args.report:
        args.report.write_text(text)
    verdict = report.verdict
    if args.expect_failure and verdict != PENDING:
        if verdict == FAIL and args.expect_failure in report.failed():
            print(f"negative control: {args.expect_failure} failed as expected")
            return 0
        print(f"negative control: expected {args.expect_failure} to fail the run", file=sys.stderr)
        return 1
    return EXIT[verdict]


if __name__ == "__main__":
    sys.exit(main())
