"""Keep the fast-lane service masks in e2e.yml and the startup inventory in sync.

The fast QEMU lane masks shipped units before first boot. Each masked unit must
be classified in startup_service_inventory.yaml so a masked startup path is
never mistaken for qualified startup coverage (#1025).
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "e2e.yml"
INVENTORY = REPO / "startup_service_inventory.yaml"

CATEGORIES = {"startup_contract", "vm_inapplicable", "ci_noise"}
MASK_SITES = {"kernel_args", "deployment_symlink"}
SYMLINK_SUFFIXES = (".service", ".socket", ".path", ".timer")
UNIT_SUFFIX = re.compile(r"\.(service|socket|path|timer|target|mount)$")


def kernel_arg_masks(workflow: str) -> set[str]:
    match = re.search(r'^\s*KERNEL_ARGS="([^"]*)"', workflow, re.MULTILINE)
    assert match, "KERNEL_ARGS assignment not found in e2e.yml"
    return set(re.findall(r"systemd\.mask=(\S+)", match.group(1)))


def symlink_loop_tokens(workflow: str) -> list[str]:
    match = re.search(
        r"for svc in ([^;\n]+); do\n"
        r'\s*sudo ln -sf /dev/null "\$\{DEP\}/etc/systemd/system/\$\{svc\}\.service"',
        workflow,
    )
    assert match, "deployment mask loop not found in e2e.yml"
    return match.group(1).split()


def symlink_masks(tokens: list[str]) -> set[str]:
    """Unit names the loop actually masks: every token gets all four suffixes."""
    return {token + suffix for token in tokens for suffix in SYMLINK_SUFFIXES}


@pytest.fixture(scope="module")
def workflow() -> str:
    return WORKFLOW.read_text()


@pytest.fixture(scope="module")
def inventory() -> dict:
    return yaml.safe_load(INVENTORY.read_text())["units"]


def test_kernel_arg_parser_reads_masks():
    sample = 'KERNEL_ARGS="rw systemd.mask=a.service systemd.wants=sshd.service systemd.mask=b.timer"'
    assert kernel_arg_masks(sample) == {"a.service", "b.timer"}


def test_symlink_masks_expand_bare_tokens_only_meaningfully():
    masked = symlink_masks(["cups", "cups.path"])
    assert {"cups.service", "cups.socket", "cups.path", "cups.timer"} <= masked
    assert "cups.path.service" in masked  # dotted token: no real unit
    assert "cups.path" in masked  # covered by the bare token, not the dotted one


def test_every_masked_unit_is_classified(workflow, inventory):
    kernel = kernel_arg_masks(workflow)
    tokens = symlink_loop_tokens(workflow)
    missing = sorted(kernel - inventory.keys())
    assert not missing, f"masked in KERNEL_ARGS but not inventoried: {missing}"

    for token in tokens:
        if UNIT_SUFFIX.search(token):
            continue  # dotted tokens only add nonexistent *.path.service names
        produced = {token + suffix for suffix in SYMLINK_SUFFIXES}
        assert produced & inventory.keys(), (
            f"deployment mask loop token {token!r} masks no inventoried unit"
        )


def test_inventory_mask_sites_match_workflow(workflow, inventory):
    kernel = kernel_arg_masks(workflow)
    linked = symlink_masks(symlink_loop_tokens(workflow))
    for unit, entry in inventory.items():
        actual = set()
        if unit in kernel:
            actual.add("kernel_args")
        if unit in linked:
            actual.add("deployment_symlink")
        assert actual, f"{unit} is inventoried but no longer masked; drop the entry"
        assert set(entry["mask_sites"]) == actual, (
            f"{unit}: inventory says {sorted(entry['mask_sites'])}, e2e.yml has {sorted(actual)}"
        )


def test_inventory_entries_are_well_formed(inventory):
    for unit, entry in inventory.items():
        assert UNIT_SUFFIX.search(unit), f"{unit}: not a systemd unit name"
        assert entry["category"] in CATEGORIES, f"{unit}: bad category"
        assert set(entry["mask_sites"]) <= MASK_SITES, f"{unit}: bad mask site"
        if entry["category"] == "startup_contract":
            assert entry.get("profiles"), f"{unit}: startup_contract needs profiles"
            assert entry.get("evidence"), f"{unit}: startup_contract needs evidence"
            assert "fast_lane_substitute" in entry, (
                f"{unit}: say what the fast lane does instead, or 'none'"
            )
        else:
            assert entry.get("reason"), f"{unit}: masking needs a reason"


def test_first_boot_contract_units_are_not_downgraded(inventory):
    """The units #1025 names must stay startup_contract until a lane runs them."""
    for unit in (
        "brew-setup.service",
        "flatpak-preinstall.service",
        "greenboot-healthcheck.service",
        "greenboot-set-rollback-trigger.service",
        "podman-auto-update.timer",
    ):
        assert inventory[unit]["category"] == "startup_contract", unit
