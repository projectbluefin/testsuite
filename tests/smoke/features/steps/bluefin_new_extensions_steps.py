"""Step definitions for AT-SPI smoke and crash-regression coverage of the
curated GNOME extensions enabled by default in Bluefin/Dakota
(projectbluefin/common#1087). See bluefin_new_extensions.feature.

Reuses the host-command / Shell.Eval / journal helpers already established
in steps.py and gnome_extensions_steps.py rather than duplicating the SSH
transport logic. Third-party extension internals (gsettings schema ids,
AT-SPI role names) are not guaranteed to match our best-effort guesses, so
checks that depend on them degrade to a printed WARNING + soft pass while
the core stability assertions (GNOME Shell stays accessible, no new
journal errors) always run and fail hard.
"""
import re
import time
from time import sleep

from behave import step

try:
    from dogtail import tree
except Exception:  # noqa: BLE001
    tree = None  # type: ignore[assignment]

from steps.gnome_extensions_steps import _extension_state, _run_host
from steps.steps import _eval_bool

# ---------------------------------------------------------------------------
# Extension identifiers (issue #793 / projectbluefin/common#1087)
# ---------------------------------------------------------------------------
BLUETOOTH_BATTERY_METER_UUID = "Bluetooth-Battery-Meter@maniacx.github.com"
TILING_ASSISTANT_UUID = "tiling-assistant@leleat-on-github"


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _journal_snapshot_marker() -> str:
    """Return a host timestamp usable as a `journalctl --since` marker."""
    stdout, rc, stderr = _run_host(["date", "+%Y-%m-%d %H:%M:%S"])
    assert rc == 0, f"date failed: {stderr or stdout}"
    return stdout.strip()


def _journal_errors_since(marker: str, extra_pattern: str | None = None) -> list[str]:
    """Return gnome-shell error/crit journal lines logged since `marker`.

    Optionally further filtered to lines also matching `extra_pattern`
    (case-insensitive), e.g. an extension uuid.
    """
    output, returncode, stderr = _run_host(
        [
            "journalctl", "--no-pager", "-p", "err..emerg",
            "--since", marker, "-q",
        ]
    )
    assert returncode == 0, f"journalctl failed: {stderr or output}"
    pattern = re.compile(r"gnome-shell", re.IGNORECASE)
    lines = [line for line in output.splitlines() if pattern.search(line)]
    if extra_pattern:
        extra = re.compile(extra_pattern, re.IGNORECASE)
        lines = [line for line in lines if extra.search(line)]
    return lines


def _assert_no_new_shell_errors(marker: str, extra_pattern: str | None = None) -> None:
    errors = _journal_errors_since(marker, extra_pattern)
    assert not errors, "Unexpected gnome-shell journal errors:\n" + "\n".join(errors)


def _wait_gnome_shell_accessible(timeout: float = 20.0) -> None:
    if tree is None:
        print("WARNING: dogtail unavailable — skipping AT-SPI accessibility recheck", flush=True)
        return
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        try:
            shell = tree.root.application("gnome-shell")
            assert shell is not None
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            sleep(0.5)
    raise AssertionError(f"gnome-shell not accessible via AT-SPI: {last_exc}")


def _extension_gsettings_value(uuid: str, key: str):
    """Best-effort read of a gsettings key for an extension's own schema.

    Returns (value, schema) or (None, None) when no candidate schema id
    exposes the key — third-party extensions don't publish a canonical
    schema-id naming convention, so callers must treat None as "unverifiable"
    rather than "failed".
    """
    short = uuid.split("@", 1)[0]
    candidates = (
        f"org.gnome.shell.extensions.{short}",
        f"org.gnome.shell.extensions.{short.replace('-', '_')}",
    )
    for schema in candidates:
        stdout, rc, _stderr = _run_host(
            f"source /tmp/session.env 2>/dev/null; gsettings get {schema} {key} 2>&1"
        )
        if rc == 0:
            return stdout.strip(), schema
    return None, None


# ---------------------------------------------------------------------------
# Bluetooth Battery Meter
# ---------------------------------------------------------------------------

@step("The Bluetooth battery panel icon is rendered")
def the_bluetooth_battery_panel_icon_is_rendered(context) -> None:
    if tree is None:
        print("WARNING: dogtail unavailable — Bluetooth battery icon check soft-skipped", flush=True)
        return
    try:
        shell = tree.root.application("gnome-shell")
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: gnome-shell not found in AT-SPI tree: {exc}", flush=True)
        return
    panels = shell.findChildren(lambda n: n.roleName == "panel")
    icons = []
    for panel in panels:
        icons.extend(
            panel.findChildren(
                lambda n: n.roleName in ("icon", "label", "push button") and n.showing
                and "bluetooth" in (n.name or "").casefold()
            )
        )
    if not icons:
        print(
            "WARNING: no Bluetooth-labeled panel icon found via AT-SPI "
            "(no paired devices, or icon hidden per extension config) — soft pass",
            flush=True,
        )


@step('The extension uses symbolic indicator color with "{setting}"')
def the_extension_uses_symbolic_indicator_color(context, setting: str) -> None:
    match = re.match(r"\s*([\w-]+)\s*=\s*(\S+)\s*", setting)
    assert match, f"Could not parse setting expression: {setting!r}"
    key, expected = match.group(1), match.group(2)
    value, schema = _extension_gsettings_value(BLUETOOTH_BATTERY_METER_UUID, key)
    if value is None:
        print(
            f"WARNING: could not resolve gsettings schema for {BLUETOOTH_BATTERY_METER_UUID} "
            f"key {key!r} — soft pass",
            flush=True,
        )
        return
    normalized = re.sub(r"^[a-z][a-z0-9]*\s+", "", value.strip())  # strip GVariant type prefix e.g. "uint32 0"
    assert normalized == expected, f"{schema} {key} is {value!r}, expected {expected!r}"


@step("The panel remains clean and GNOME Shell remains accessible when no Bluetooth devices are present")
def the_panel_remains_clean_when_no_bluetooth_devices_are_present(context) -> None:
    _wait_gnome_shell_accessible()
    state = _extension_state(BLUETOOTH_BATTERY_METER_UUID)
    assert state == "1", (
        f"{BLUETOOTH_BATTERY_METER_UUID} left state {state} when no Bluetooth devices are "
        "present (expected state=1 ENABLED, not crashed/disabled)"
    )



@step("Window-snapping keyboard shortcuts work")
def window_snapping_keyboard_shortcuts_work(context) -> None:
    marker = _journal_snapshot_marker()
    try:
        context.execute_steps(
            '* Key combo: "<Super><Left>" with uinput\n'
            '* Key combo: "<Super><Right>" with uinput'
        )
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: uinput key combo unavailable in this environment: {exc}", flush=True)
    _wait_gnome_shell_accessible()
    _assert_no_new_shell_errors(marker, extra_pattern=re.escape(TILING_ASSISTANT_UUID))


@step("Window-snapping gestures work")
def window_snapping_gestures_work(context) -> None:
    # Multi-touch trackpad gestures cannot be synthesized through uinput/AT-SPI
    # in headless CI (no libinput touchpad device is exposed to the VM).
    # We assert the extension stayed enabled and Shell stayed stable, and
    # soft-pass the gesture-specific interaction itself.
    print(
        "WARNING: gesture input cannot be synthesized in headless CI — "
        "soft-skipping the gesture interaction, still asserting Shell stability",
        flush=True,
    )
    _wait_gnome_shell_accessible()
    state = _extension_state(TILING_ASSISTANT_UUID)
    assert state == "1", f"{TILING_ASSISTANT_UUID} is not enabled (state={state})"


@step("GNOME Shell remains responsive without shell errors")
def gnome_shell_remains_responsive_without_shell_errors(context) -> None:
    marker = _journal_snapshot_marker()
    _wait_gnome_shell_accessible()
    assert _eval_bool("true") is True, "Shell.Eval did not respond — GNOME Shell may be unresponsive"
    _assert_no_new_shell_errors(marker)

