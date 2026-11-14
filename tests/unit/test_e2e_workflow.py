"""Regression checks for shared E2E workflow setup."""

from pathlib import Path


def _workflow(name: str) -> str:
    return (
        Path(__file__).parents[2] / ".github" / "workflows" / name
    ).read_text()


def test_e2e_preserves_image_enabled_extensions():
    workflow = _workflow("e2e.yml")
    local_override = workflow.partition(
        'sudo mkdir -p "${DEP}/etc/dconf/db/local.d"'
    )[2].partition("sudo chroot")[0]

    assert "allow-extension-installation=true" in local_override
    assert "enabled-extensions" not in local_override
    assert "gnome-extensions enable unsafe-mode@bluefin-test" in workflow


def test_e2e_keeps_tailscale_running_with_sufficient_storage():
    workflow = _workflow("e2e.yml")

    assert "fallocate -l 40G disk.raw" in workflow
    assert "systemd.mask=tailscaled.service" not in workflow
    assert "idle-delay 0" in workflow
    assert "lock-enabled false" in workflow
    assert "pkill -x gnome-initial-setup" not in workflow


def test_manual_runs_checkout_the_selected_fork_ref_without_changing_callers():
    reusable = _workflow("e2e.yml")
    manual = _workflow("manual.yml")

    assert 'default: "projectbluefin/testsuite"' in reusable
    assert "repository: ${{ inputs.test_repository }}" in reusable
    assert "test_repository: ${{ github.repository }}" in manual


def test_e2e_ci_user_tmpfiles_has_no_recursive_home_relabel():
    # A recursive `Z` on the test home walks the runner's Podman storage on
    # every later boot and trips systemd-tmpfiles SELinux denials (#1205).
    workflow = _workflow("e2e.yml")
    start = workflow.index('"${DEP}/etc/tmpfiles.d/"')
    block = workflow[start:workflow.index("ci-user.conf", start)]
    assert "'Z " not in block and "\\nZ " not in block
    assert "d /var/home/bluefin-test 0700" in block
    assert "d /var/home/bluefin-test/.ssh 0700" in block
