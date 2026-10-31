"""FlatPark remote and Compass (org.tunaos.compass) lifecycle steps.

Every command runs on the VM through the shared ``run_ssh`` helper; the
install path uses ``Run long SSH command`` from the feature because the
extra-data payload (a ~71 MB AppImage) is fetched from GitHub at install time,
far beyond ``_flatpak``'s 10 s timeout.
"""
from __future__ import annotations

from behave import step

from tests.shared.ssh_steps import run_ssh

try:  # behave loads the suite steps directory as a top-level ``steps`` package
    from steps.flatpak_permissions_steps import context_values, parse_flatpak_context
except ImportError:  # pytest / direct module import
    from tests.software.features.steps.flatpak_permissions_steps import (
        context_values,
        parse_flatpak_context,
    )

COMPASS_APP_ID = "org.tunaos.compass"
# Written before the uninstall to prove `flatpak uninstall` without
# --delete-data keeps ~/.var/app; cleanup removes only this file.
COMPASS_DATA_MARKER = "~/.var/app/org.tunaos.compass/config/compass/testsuite-uninstall-marker"

# Filesystem grants that expose the user's home directory.
_HOME_GRANTS = {"home", "~", "host"}


def parse_flatpak_info(text: str) -> dict[str, str]:
    """Parse ``flatpak info`` ``Key: value`` lines (keys are right-aligned)."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and " " not in key.strip():
            fields.setdefault(key.strip(), value.strip())
    return fields


def remote_filters(text: str) -> dict[str, str]:
    """Map remote name → filter path from ``flatpak remotes --columns=name,filter``."""
    filters: dict[str, str] = {}
    for line in text.splitlines():
        name, _, path = line.partition("\t")
        if name.strip():
            filters[name.strip()] = path.strip()
    return filters


def home_grants(filesystems: list[str]) -> list[str]:
    """Return the filesystem grants that reach the home directory.

    ``!home`` is a revocation, not a grant; ``home:ro`` still exposes home.
    """
    return [
        item for item in filesystems
        if not item.startswith("!") and item.split(":", 1)[0] in _HOME_GRANTS
    ]


def _checked(context, cmd: str, timeout: int = 60) -> str:
    stdout, rc = run_ssh(context, cmd, timeout=timeout)
    result = getattr(context, "last_ssh_result", None)
    assert rc == 0, (
        f"`{cmd}` exited {rc}\nstdout: {stdout}\n"
        f"stderr: {getattr(result, 'stderr', '')}"
    )
    return stdout


def _remove_compass(context) -> None:
    """Uninstall the system Compass if present and drop the data marker."""
    _checked(context, f"rm -f {COMPASS_DATA_MARKER}")
    _, rc = run_ssh(context, f"flatpak info --system {COMPASS_APP_ID} >/dev/null 2>&1")
    if rc == 0:
        _checked(
            context,
            f"sudo -n flatpak uninstall -y --system {COMPASS_APP_ID}",
            timeout=300,
        )


@step("the VM is x86_64, the only arch FlatPark builds Compass for")
def vm_is_x86_64_for_compass(context) -> None:
    # FlatPark's manifest pins both extra-data sources to `only-arches: x86_64`,
    # so on aarch64 there is no ref to install: skip, do not fail.
    arch = _checked(context, "uname -m")
    if arch != "x86_64":
        context.scenario.skip(f"FlatPark ships org.tunaos.compass for x86_64 only, VM is {arch!r}")


@step('the image enables GNOME Shell extension "{uuid}" by default')
def image_enables_shell_extension_by_default(context, uuid: str) -> None:
    # The memory backend ignores the user's dconf, so this reads the compiled
    # schema default (common's zz0-bluefin-modifications override, where the
    # image ships it). Images that do not enable it skip: the default differs
    # across the Bluefin family and by common pin.
    enabled = _checked(context, "GSETTINGS_BACKEND=memory gsettings get org.gnome.shell enabled-extensions")
    if f"'{uuid}'" not in enabled:
        context.scenario.skip(f"image does not enable {uuid} by default: {enabled}")


@step("Compass is absent now and removed again when the scenario ends")
def compass_absent_with_cleanup(context) -> None:
    _remove_compass(context)
    context.add_cleanup(_remove_compass, context)


@step('Flatpak system remote "{name}" uses filter "{path}"')
def flatpak_system_remote_uses_filter(context, name: str, path: str) -> None:
    filters = remote_filters(
        _checked(context, "flatpak remotes --system --columns=name,filter:f")
    )
    assert name in filters, f"System remote {name!r} not configured: {sorted(filters)}"
    assert filters[name] == path, (
        f"System remote {name!r} filter is {filters[name]!r}, expected {path!r}"
    )
    _checked(context, f"test -f {path}")


@step('Flatpak system app "{app_id}" reports origin "{origin}", branch "{branch}" and arch "{arch}"')
def flatpak_system_app_reports_ref(context, app_id: str, origin: str, branch: str, arch: str) -> None:
    fields = parse_flatpak_info(_checked(context, f"flatpak info --system {app_id}"))
    actual = {key: fields.get(key) for key in ("Origin", "Branch", "Arch")}
    expected = {"Origin": origin, "Branch": branch, "Arch": arch}
    assert actual == expected, f"flatpak info --system {app_id}: {actual}, expected {expected}"


def _permissions(context, app_id: str) -> str:
    return _checked(context, f"flatpak info --system --show-permissions {app_id}")


@step('Flatpak system app "{app_id}" permission "{section}" sets "{key}" to "{value}"')
def flatpak_system_app_permission_sets(context, app_id: str, section: str, key: str, value: str) -> None:
    output = _permissions(context, app_id)
    actual = parse_flatpak_context(output).get(section, {}).get(key)
    assert actual == value, (
        f"[{section}] {key} is {actual!r} for {app_id}, expected {value!r}:\n{output}"
    )


@step('Flatpak system app "{app_id}" filesystem permissions include "{grant}"')
def flatpak_system_app_filesystems_include(context, app_id: str, grant: str) -> None:
    output = _permissions(context, app_id)
    assert grant in context_values(output, "filesystems"), (
        f"{app_id} lacks filesystem grant {grant!r}:\n{output}"
    )


@step('Flatpak system app "{app_id}" has no home filesystem grant')
def flatpak_system_app_has_no_home_grant(context, app_id: str) -> None:
    output = _permissions(context, app_id)
    grants = home_grants(context_values(output, "filesystems"))
    assert not grants, f"{app_id} grants home access via {grants}:\n{output}"
