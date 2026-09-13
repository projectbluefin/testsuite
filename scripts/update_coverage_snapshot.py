#!/usr/bin/env python3
"""Regenerate the Coverage snapshot table in suite-map/SKILL.md.

The per-suite scenario counts are computed by parsing the tags on every
scenario in ``tests/*/features/**/*.feature`` so they are always accurate and
never hand-edited. Hand-editing those numbers is the root cause of the
merge-queue conflict storms (every test PR used to touch the same table).

Tag precedence (a scenario counts exactly once):
    @quarantine > @hardware_blocked > @future > @pending > active

The "Pending/Future" column is the non-runnable backlog: ``@pending`` +
``@future`` + ``@hardware_blocked``. Only the per-suite ``Notes`` prose is
hand-maintained, in the ``SUITE_NOTES`` mapping below.

Rewrites the content between the ``<!-- coverage-snapshot:start -->`` and
``<!-- coverage-snapshot:end -->`` markers in the suite-map skill. With
``--check`` it exits non-zero if the committed table is stale, so CI can
enforce regeneration instead of manual edits.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

MARKER_START = "<!-- coverage-snapshot:start -->"
MARKER_END = "<!-- coverage-snapshot:end -->"
SUITE_MAP = Path("docs/skills/test-authoring/suite-map/SKILL.md")

TAG_RE = re.compile(r"@([\w-]+)")
SCENARIO_RE = re.compile(r"^\s*(?:Scenario|Scenario Outline)\s*:")

# Hand-maintained prose per suite. Numbers are computed; only this column is
# edited by humans, and only when a suite's *purpose* changes (rarely).
SUITE_NOTES: dict[str, str] = {
    "smoke": "39 `@pending` flatpak-permission audits blocked on CI never seeding system Flatpaks; MIME handler coverage (Firefox/Papers/Loupe/Text Editor/video); GNOME accessibility (AT-SPI daemon, high-contrast toggle, a11y panel); display fractional/integer scaling via Mutter DisplayConfig; Bluefin desktop identity (Wayland, hardware accel, Dash to Dock); GNOME regression guards in gnome_regression.feature; Dakota sudo-rs privilege and PAM checks",
    "developer": "6 brew + 6 ptyxis now `@pending`: `brew-setup.service` masked in CI (#487) and the ptyxis AT-SPI restart issue (#368)",
    "software": "Bazaar launch + search + CLI presence/info/remote + config YAML validation active on bluefin; Bazaar UI tests rewritten for actual Bazaar layout; CLI (Flathub remote + permissions DB) active on all images; Flatpak per-app permission management active on all images; upstream GNOME Software scenarios are `@future` (#847)",
    "common": "Signing assertions `@future` pending the ublue-os→projectbluefin policy migration; flatpak model/state, dconf defaults, and immutability checks `@pending` on CI infra (#838); Flatpak model + state; XDG portal health + integration; container runtime (podman); polkit rules; shell env + sourcing; system scripts; ujust recipes; GSettings/dconf defaults; immutable OS integrity; desktop entries; signing assertions; Dakota `ujust --choose` regression guard active (`@dakota_only`); `ujust report` is `@pending` on #706 until a Dakota lab run validates the mocked submit flow",
    "vanilla-gnome": "Baseline GNOME Shell parity check; runs on any GNOME image; org.gnome.desktop.a11y.interface reduced-motion + keyboard-focus-visible-timeout gsettings round-trips (@requires_gnome_51, skip on GNOME <= 50 via runtime Shell version probe)",
    "lifecycle": "bootc upgrade / rollback / migration; switch is `@future` (needs a valid alternate image ref; pin activated with settled-deployment barrier)",
    "hardware": "udev rules syntax validation (ZSA, Apple SuperDrive, Framework 16, AMD s2idle, Wooting, VIIA); emulated peripherals driven by shared SSH steps",
    "security": "cosign verify: projectbluefin (bluefin, lts, dakota) + ublue-os (latest, LTS, DX, nvidia, GTS, DX-nvidia, negative)",
    "bazzite": "Extension presence + shell behaviour",
    "dx": "distrobox create/install/export are active behind the `@requires_cached_image` runtime gate — they skip until `fedora-toolbox:latest` is pre-pulled on the VM (#501 / projectbluefin/lab#621) and activate without a feature-file edit; distrobox enter, JupyterLab, brew, mise remain `@pending` on infra gaps",
    "nvidia": "`@future` / `@hardware_blocked` until GPU passthrough exists in the lab",
    "flatcar": "boot (7 active) + lifecycle (5 active); 1 `@future` (boot from installed target disk — needs KubeVirt boot-order support in `projectbluefin/lab`)",
    "kde-smoke": "Plasma session, D-Bus services, AT-SPI tree, KWin output, one KCM, Dolphin, Konsole, Kickoff; all `@informational`",
    "installer": "post-boot assertions for installer-driven installs (UEFI, Flatpak exclusion, LUKS cmdline)",
}


@dataclass
class SuiteCounts:
    name: str
    active: int = 0
    quarantined: int = 0
    pending: int = 0  # @pending + @future + @hardware_blocked (non-runnable backlog)

    @property
    def total(self) -> int:
        return self.active + self.quarantined + self.pending


def parse_scenarios(content: str) -> list[set[str]]:
    """Return the effective tag set for each scenario (feature tags inherited)."""
    feature_tags: tuple[str, ...] = ()
    pending_tags: list[str] = []
    scenarios: list[set[str]] = []

    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("@"):
            pending_tags.extend(TAG_RE.findall(stripped))
            continue
        if stripped.startswith("Feature:"):
            feature_tags = tuple(pending_tags)
            pending_tags = []
            continue
        if SCENARIO_RE.match(raw_line):
            scenarios.append(set(feature_tags) | set(pending_tags))
            pending_tags = []
            continue
        if stripped.startswith(("Rule:", "Background:", "Examples:")):
            pending_tags = []
    return scenarios


def classify(tags: set[str]) -> str:
    """Tag precedence: quarantine > hardware_blocked > future > pending > active."""
    if "quarantine" in tags:
        return "quarantined"
    if tags & {"hardware_blocked", "future", "pending"}:
        return "pending"
    return "active"


def count_scenarios(repo_root: Path) -> dict[str, SuiteCounts]:
    suites: dict[str, SuiteCounts] = {}
    tests_root = repo_root / "tests"
    for feature in sorted(tests_root.rglob("*.feature")):
        suite = feature.relative_to(tests_root).parts[0]
        suite_counts = suites.setdefault(suite, SuiteCounts(name=suite))
        for tags in parse_scenarios(feature.read_text(encoding="utf-8")):
            bucket = classify(tags)
            setattr(suite_counts, bucket, getattr(suite_counts, bucket) + 1)
    return suites


def render_snapshot(repo_root: Path) -> str:
    suites = count_scenarios(repo_root)
    total = sum(c.total for c in suites.values())
    active = sum(c.active for c in suites.values())
    quarantined = sum(c.quarantined for c in suites.values())
    pending = sum(c.pending for c in suites.values())
    feature_files = sum(1 for _ in (repo_root / "tests").rglob("*.feature"))

    lines = [
        MARKER_START,
        "",
        f"{total} scenarios across {feature_files} feature files: "
        f"{active} active, {quarantined} quarantined, "
        f"{pending} `@future`/`@pending`/`@hardware_blocked`",
        "",
        "| Suite | Scenarios | Active | Quarantined | Pending/Future | Notes |",
        "|---|---|---|---|---|---|",
    ]
    for suite in sorted(suites):
        c = suites[suite]
        note = SUITE_NOTES.get(suite, "")
        lines.append(
            f"| {suite} | {c.total} | {c.active} | {c.quarantined} | {c.pending} | {note} |"
        )
    lines += ["", MARKER_END]
    return "\n".join(lines)


def update_file(repo_root: Path, check: bool) -> int:
    path = repo_root / SUITE_MAP
    text = path.read_text(encoding="utf-8")

    if MARKER_START not in text or MARKER_END not in text:
        print(f"error: markers not found in {SUITE_MAP}", file=sys.stderr)
        print(f"add {MARKER_START} and {MARKER_END} around the snapshot table",
              file=sys.stderr)
        return 2

    start = text.index(MARKER_START)
    end = text.index(MARKER_END) + len(MARKER_END)
    new_block = render_snapshot(repo_root)
    new_text = text[:start] + new_block + text[end:]

    if check:
        if new_text != text:
            print(f"STALE: {SUITE_MAP} coverage snapshot is out of date.")
            print("Run: python3 scripts/update_coverage_snapshot.py")
            return 1
        print(f"OK: {SUITE_MAP} coverage snapshot is up to date.")
        return 0

    if new_text == text:
        print("No change — snapshot already current.")
        return 0
    path.write_text(new_text, encoding="utf-8")
    print(f"Updated {SUITE_MAP}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the snapshot is stale (for CI)")
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    return update_file(args.repo_root.resolve(), args.check)


if __name__ == "__main__":
    raise SystemExit(main())
