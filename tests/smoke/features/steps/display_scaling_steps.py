"""Custom step definitions for display fractional scaling smoke checks.

Uses Mutter's org.gnome.Mutter.DisplayConfig D-Bus API to read and apply
monitor scaling. All session-bus access is forwarded to the VM via SSH when
running inside the runner container.
"""

import ast
import json
import os
import re
import shlex
import subprocess
from time import sleep

from tests.shared.ssh_config import ssh_argv

from behave import step

try:
    from qecore.common_steps import *  # noqa: F401,F403
except Exception:  # noqa: BLE001
    pass


# Same container detection as system_health_steps — /proc/1/ns/mnt is a symlink
# to a kernel namespace object so lexists() is required (isfile() returns False).
_IN_CONTAINER = os.path.lexists("/proc/1/ns/mnt") and not os.path.isfile("/usr/bin/bootc")

_MUTTER_EXPERIMENTAL_FEATURES_KEY = "org.gnome.mutter experimental-features"
_FRACTIONAL_SCALE_FEATURE = "scale-monitor-framebuffer"


def _ssh_args() -> list[str]:
    """Canonical SSH argv — see tests/shared/ssh_config.py."""
    return ssh_argv()


def _run_host(cmd: str, timeout: int = 30):
    """Run cmd on the host VM via SSH when inside the runner container."""
    if _IN_CONTAINER:
        result = subprocess.run(
            _ssh_args() + [cmd],
            capture_output=True, text=True, timeout=timeout,
        )
    else:
        env = dict(os.environ)
        if not env.get("DBUS_SESSION_BUS_ADDRESS"):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{os.getuid()}/bus"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=env,
        )
    return result.stdout.strip(), result.returncode, result.stderr.strip()


def _session_env_prefix() -> str:
    return "source /tmp/session.env 2>/dev/null; "


def _with_session_env(cmd: str) -> str:
    """Prepend session environment sourcing when running inside the container."""
    if _IN_CONTAINER:
        return _session_env_prefix() + cmd
    return cmd


def _gnome_shell_major_version() -> int | None:
    """Return the GNOME Shell major version, or None if it cannot be parsed."""
    stdout, rc, _ = _run_host(
        _with_session_env(
            "gnome-shell --version 2>/dev/null || mutter --version 2>/dev/null"
        )
    )
    if rc != 0 or not stdout:
        return None
    match = re.search(r"(\d+)\.\d+", stdout)
    if match:
        return int(match.group(1))
    return None


# Embedded helper script that runs on the VM and talks to Mutter over the
# session bus. Kept as a single string so it can be passed via SSH without
# creating files on the test runner filesystem.
_DISPLAY_CONFIG_SCRIPT = r'''
import dbus
import json
import sys


def _native(value):
    if isinstance(value, dbus.Boolean):
        return bool(value)
    if isinstance(value, (dbus.Int32, dbus.Int64, dbus.UInt32, dbus.UInt64)):
        return int(value)
    if isinstance(value, dbus.Double):
        return float(value)
    if isinstance(value, dbus.String):
        return str(value)
    if isinstance(value, dbus.Array):
        return [_native(v) for v in value]
    if isinstance(value, dbus.Dictionary):
        return {_native(k): _native(v) for k, v in value.items()}
    return value


def _find_current_mode(monitor):
    """Return the currently-active mode tuple from a top-level monitor."""
    modes = monitor[1]
    for mode in modes:
        props = dict(mode[6])
        if props.get("is-current", False):
            return mode
    for mode in modes:
        props = dict(mode[6])
        if props.get("is-preferred", False):
            return mode
    if modes:
        return modes[0]
    raise RuntimeError(f"No modes available for monitor {monitor[0][0]}")


def _find_current_mode_id(monitor):
    """Return the ID of the currently-active mode from a top-level monitor."""
    return str(_find_current_mode(monitor)[0])


def _supported_scales(monitor):
    """Return the supported scales list for the currently-active mode."""
    mode = _find_current_mode(monitor)
    return list(mode[5])


def _common_supported_scales():
    """Return the set of scales supported by every logical monitor."""
    iface = _get_interface()
    serial, monitors, logical_monitors, properties = iface.GetCurrentState()
    monitors_by_id = {
        (str(m[0][0]), str(m[0][1]), str(m[0][2]), str(m[0][3])): m
        for m in monitors
    }
    common = None
    for lm in logical_monitors:
        for m in lm[5]:
            key = (str(m[0]), str(m[1]), str(m[2]), str(m[3]))
            top_monitor = monitors_by_id[key]
            lm_supported = set(float(s) for s in _supported_scales(top_monitor))
            common = lm_supported if common is None else common & lm_supported
    return common if common is not None else set()


def _choose_supported_scale(target):
    """Return the supported scale nearest to target, preferring <= target."""
    target = float(target)
    common = _common_supported_scales()
    if not common:
        raise RuntimeError("No common supported scales for current monitors")
    candidates = sorted(s for s in common if s > 1.0)
    if not candidates:
        raise RuntimeError("No scaling (>1.0) supported for current monitors")
    if target in common:
        return target
    lower = [s for s in candidates if s <= target]
    upper = [s for s in candidates if s > target]
    if lower and upper:
        return lower[-1] if (target - lower[-1]) <= (upper[0] - target) else upper[0]
    return lower[-1] if lower else upper[0]


def _build_logical_monitor(lm, monitors_by_id, new_scale=None):
    """Build an ApplyMonitorsConfig logical monitor from a GetCurrentState one."""
    previous_scale = float(lm[2])
    scale = float(new_scale) if new_scale is not None else float(lm[2])
    # Mutter positions monitors in logical pixels.  When a scale changes, retain
    # the physical layout by converting the existing logical coordinates.
    x = round(int(lm[0]) * previous_scale / scale)
    y = round(int(lm[1]) * previous_scale / scale)
    transform = int(lm[3])
    primary = bool(lm[4])
    monitors = []
    for m in lm[5]:
        connector = str(m[0])
        vendor = str(m[1])
        product = str(m[2])
        serial = str(m[3])
        key = (connector, vendor, product, serial)
        top_monitor = monitors_by_id.get(key)
        if top_monitor is None:
            raise RuntimeError(f"Monitor {key} not found in top-level monitors")
        mode_id = _find_current_mode_id(top_monitor)
        monitors.append((connector, mode_id, dbus.Dictionary({}, signature="sv")))
    return (x, y, scale, transform, primary, monitors)


def _get_interface():
    bus = dbus.SessionBus()
    proxy = bus.get_object(
        "org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig"
    )
    return dbus.Interface(proxy, "org.gnome.Mutter.DisplayConfig")


def _get_state():
    iface = _get_interface()
    serial, monitors, logical_monitors, properties = iface.GetCurrentState()
    monitors_by_id = {
        (str(m[0][0]), str(m[0][1]), str(m[0][2]), str(m[0][3])): m
        for m in monitors
    }
    return {
        "serial": _native(serial),
        "logical_monitors": [
            {
                "x": _native(lm[0]),
                "y": _native(lm[1]),
                "scale": _native(lm[2]),
                "transform": _native(lm[3]),
                "primary": _native(lm[4]),
                "monitors": [
                    {
                        "connector": _native(m[0]),
                        "current_mode": _find_current_mode_id(
                            monitors_by_id[
                                (
                                    str(m[0]),
                                    str(m[1]),
                                    str(m[2]),
                                    str(m[3]),
                                )
                            ]
                        ),
                    }
                    for m in lm[5]
                ],
            }
            for lm in logical_monitors
        ],
    }


def _apply_scale(scale, method=1):
    """Apply a scale to all current logical monitors. method=1 is temporary."""
    iface = _get_interface()
    serial, monitors, logical_monitors, properties = iface.GetCurrentState()
    monitors_by_id = {
        (str(m[0][0]), str(m[0][1]), str(m[0][2]), str(m[0][3])): m
        for m in monitors
    }

    # Validate that the requested scale is supported by every logical monitor's
    # current mode so Mutter's ApplyMonitorsConfig gives a clear error up front.
    supported = _common_supported_scales()
    if scale not in supported:
        raise RuntimeError(
            f"Scale {scale} is not supported for the current resolution; "
            f"supported scales: {sorted(supported)}"
        )

    new_logical_monitors = [
        _build_logical_monitor(lm, monitors_by_id, scale)
        for lm in logical_monitors
    ]
    iface.ApplyMonitorsConfig(
        serial,
        method,
        new_logical_monitors,
        dbus.Dictionary({}, signature="sv"),
    )


def _get_scales():
    iface = _get_interface()
    serial, monitors, logical_monitors, properties = iface.GetCurrentState()
    return [_native(lm[2]) for lm in logical_monitors]


action = sys.argv[1]
if action == "get-state":
    print(json.dumps(_get_state()))
elif action == "apply-scale":
    scale = float(sys.argv[2])
    method = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    _apply_scale(scale, method)
    print(json.dumps({"applied": True, "scale": scale}))
elif action == "get-scales":
    print(json.dumps({"scales": _get_scales()}))
elif action == "choose-scale":
    target = float(sys.argv[2])
    chosen = _choose_supported_scale(target)
    print(json.dumps({"target": target, "scale": chosen}))
else:
    raise RuntimeError(f"Unknown action: {action}")
'''


def _display_config(action: str, *args, timeout: int = 30) -> dict:
    """Run the embedded D-Bus helper on the VM and return parsed JSON."""
    script = _DISPLAY_CONFIG_SCRIPT
    argv = " ".join(shlex.quote(str(a)) for a in args)
    cmd = f"python3 -c {shlex.quote(script)} {action} {argv}"
    stdout, rc, stderr = _run_host(_with_session_env(cmd), timeout=timeout)
    if rc != 0:
        raise AssertionError(
            f"DisplayConfig helper failed (action={action}): "
            f"rc={rc} stdout={stdout!r} stderr={stderr!r}"
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"DisplayConfig helper returned non-JSON (action={action}): "
            f"stdout={stdout!r} stderr={stderr!r}"
        ) from exc


def _apply_display_scale(scale: float, method: int = 1) -> None:
    """Apply scale to all logical monitors via Mutter DisplayConfig."""
    _display_config("apply-scale", scale, method, timeout=30)
    # Give Mutter a moment to reconfigure before callers assert.
    sleep(0.5)


def _get_display_scales() -> list[float]:
    return _display_config("get-scales", timeout=30)["scales"]


def _gsettings_get_features() -> tuple[list[str], str]:
    """Return (parsed features list, raw gsettings output)."""
    stdout, rc, stderr = _run_host(
        _with_session_env("gsettings get org.gnome.mutter experimental-features")
    )
    if rc != 0:
        # GNOME 51 graduates fractional scaling out of experimental status and
        # drops the key entirely: "No such key" means there is nothing to
        # enable, not that the read failed.
        if "No such key" in (stderr or stdout):
            print(
                "experimental-features key absent (GNOME 51+): "
                "fractional scaling needs no enabling",
                flush=True,
            )
            return [], ""
        raise AssertionError(
            f"gsettings get experimental-features failed: {stderr or stdout}"
        )
    raw = stdout.strip()
    # gsettings prints empty string arrays as '@as []'; strip the type prefix.
    parseable = raw[4:] if raw.startswith("@as ") else raw
    try:
        features = ast.literal_eval(parseable)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"Could not parse experimental-features value {raw!r}: {exc}"
        ) from exc
    if not isinstance(features, list):
        raise AssertionError(f"experimental-features is not a list: {raw!r}")
    return features, raw


def _gsettings_set_features(value: str) -> None:
    _, rc, stderr = _run_host(
        _with_session_env(
            "gsettings set org.gnome.mutter experimental-features "
            f"{shlex.quote(value)}"
        )
    )
    if rc != 0:
        raise AssertionError(
            f"gsettings set experimental-features failed: {stderr}"
        )


@step("Fractional scaling experimental feature is enabled if required")
def enable_fractional_scaling_feature_if_required(context) -> None:
    """Enable scale-monitor-framebuffer on older GNOME; store original for cleanup.

    GNOME 42+ (and therefore GNOME 50 on Bluefin) enables fractional scaling by
    default and no longer recognises scale-monitor-framebuffer as a valid
    experimental feature. On those versions we only record the original value.
    """
    features, raw = _gsettings_get_features()
    context.original_experimental_features = raw
    if _FRACTIONAL_SCALE_FEATURE in features:
        print(
            f"fractional scaling feature already enabled: {raw}",
            flush=True,
        )
        return
    major = _gnome_shell_major_version()
    if major is None:
        print(
            "could not determine GNOME Shell version; assuming fractional "
            f"scaling is available by default, leaving features as {raw}",
            flush=True,
        )
        return
    if major >= 42:
        print(
            f"GNOME Shell {major}: fractional scaling is default; "
            f"leaving experimental-features as {raw}",
            flush=True,
        )
        return
    features.append(_FRACTIONAL_SCALE_FEATURE)
    new_value = repr(features)
    _gsettings_set_features(new_value)
    context.experimental_feature_changed = True
    print(f"enabled fractional scaling feature: {new_value}", flush=True)
    # Allow mutter/gnome-settings-daemon to pick up the change.
    sleep(0.5)


@step('Set display scale to the nearest supported value of "{scale}" via Mutter DisplayConfig')
def set_display_scale(context, scale: str) -> None:
    """Apply the supported scale nearest to the requested target.

    The virtual QEMU output on the CI runner does not always support the
    exact values 1.5 or 2.0 (e.g. 1280x800 only supports [1, 1.25, 4/3, 5/3]).
    We choose the nearest supported scale, apply it, and store it so the
    assertion step can verify the actual applied value.
    """
    target = float(scale)
    chosen = _display_config("choose-scale", target, timeout=30)["scale"]
    _apply_display_scale(chosen, method=1)
    context.display_scale_changed = True
    context.display_scale_target = chosen
    print(
        f"requested scale {target}, chose supported scale {chosen}",
        flush=True,
    )


@step("Current display scale matches the applied scale")
def current_display_scale_matches_applied(context) -> None:
    """Assert every logical monitor reports the scale chosen by the previous step."""
    expected = getattr(context, "display_scale_target", None)
    assert expected is not None, "No display scale was applied in this scenario"
    scales = _get_display_scales()
    assert scales, "No logical monitors found via DisplayConfig"
    for actual in scales:
        assert abs(actual - expected) < 0.001, (
            f"Expected scale {expected}, got {actual} (all scales: {scales})"
        )


@step("GNOME Shell process is running")
def gnome_shell_process_is_running(context) -> None:
    """Assert the gnome-shell process is still alive on the VM."""
    _, rc, _ = _run_host("pgrep -x gnome-shell")
    assert rc == 0, "gnome-shell process is not running"


def _restore_display_scale(context) -> None:
    """Always return the display to 1.0 scale and restore gsettings after a test."""
    if getattr(context, "display_scale_changed", False):
        try:
            _apply_display_scale(1.0, method=1)
            print("restored display scale to 1.0", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: failed to restore display scale: {exc}", flush=True)

    if getattr(context, "experimental_feature_changed", False):
        original = getattr(context, "original_experimental_features", None)
        if original is not None:
            try:
                _gsettings_set_features(original)
                print(f"restored experimental features: {original}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"WARNING: failed to restore experimental features: {exc}",
                    flush=True,
                )
