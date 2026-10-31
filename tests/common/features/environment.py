"""
Common layer test environment — plain SSH, no qecore.

This suite validates the projectbluefin/common OCI layer by running CLI- and
GSettings-focused checks over SSH against a live Bluefin session.
"""
import os
import shlex

from tests.shared.image_family import (
    image_under_test,
    is_bluefin_image as _is_bluefin_image,
    is_dakota_image as _is_dakota_image,
)
from tests.shared.ssh_config import _first_value
from tests.shared.ssh_steps import *  # noqa: F401,F403
from tests.shared.ssh_steps import run_ssh

try:
    from tests.shared.timing import record_end, record_start
except Exception:  # noqa: BLE001
    def record_start(context):
        return None

    def record_end(context, scenario):
        return None


def _is_projectbluefin_image(image: str) -> bool:
    """Return True if the image reference is published under the projectbluefin org.

    Matches the org path segment only (e.g. "projectbluefin" in
    "ghcr.io/projectbluefin/bluefin-lts@sha256:..."), so Classic under
    ghcr.io/ublue-os, a bare image name and an empty ref all return False.
    """
    parts = image.lower().split("/")
    return len(parts) >= 2 and parts[-2] == "projectbluefin"


def _scenario_tags(scenario) -> set[str]:
    return set(getattr(scenario, "effective_tags", scenario.tags))


def _has_brew(context) -> bool:
    cached = getattr(context, "has_brew", None)
    if cached is not None:
        return cached
    _, returncode = run_ssh(
        context, "test -x /home/linuxbrew/.linuxbrew/bin/brew && test -x /home/linuxbrew/.linuxbrew/bin/fzf"
    )
    context.has_brew = returncode == 0
    return context.has_brew


def _is_container_target(context) -> bool:
    cached = getattr(context, "is_container_target", None)
    if cached is not None:
        return cached
    _, rc = run_ssh(context, "test -e /run/systemd/container")
    context.is_container_target = (rc == 0)
    return context.is_container_target


def _has_toggle_action(context) -> bool:
    """Return True when the image's toggle-updates recipe honors ACTION.

    ``ujust toggle-updates`` gained non-interactive ``ACTION=enable|disable|
    cancel`` support in projectbluefin/common (see projectbluefin/testsuite#499).
    Probe the recipe body for ``ACTION_VALUE``: the new recipe interpolates
    ``ACTION`` into ``ACTION_VALUE``, while the old recipe declares
    ``ACTION="prompt":`` but ignores it in the body and falls through to gum.
    Without a TTY, the old gum prompt fails and exits 0 on empty selection,
    so running ``ujust toggle-updates cancel`` falsely passes on old images.
    Scenarios tagged ``@requires_toggle_action`` skip until the image ships
    the contract, then activate automatically.
    """
    cached = getattr(context, "has_toggle_action", None)
    if cached is not None:
        return cached
    _, returncode = run_ssh(
        context, "ujust --show toggle-updates 2>/dev/null | grep -q 'ACTION_VALUE'"
    )
    context.has_toggle_action = returncode == 0
    return context.has_toggle_action


def _has_custom_command_list(context) -> bool:
    """Return True when the effective enabled-extensions lists custom-command-list.

    projectbluefin/common replaced Logo Menu with ``custom-command-list``
    (``zz0-bluefin-modifications.gschema.override`` + the distro dconf default
    in ``04-bluefin-custom-command-menu``). Images that build on an older
    common layer, e.g. ``ghcr.io/ublue-os/bluefin`` (Classic), still ship
    Logo Menu and carry no custom-command-list dconf keys, so the scenarios
    asserting that swap fail there for a product reason rather than a defect.
    Probe the image's effective ``enabled-extensions`` value (``gsettings
    get``, which a user override can change): scenarios tagged
    ``@requires_custom_command_list`` skip until the image ships the
    contract, then activate automatically. A failing ``gsettings`` (missing
    schema, broken dconf/D-Bus, no binary) is a defect rather than a product
    gap, so it does not skip — the scenarios run and report it. Images under
    ``ghcr.io/projectbluefin/*`` own the contract, so ``before_scenario`` never
    consults this probe for them: dropping the extension there fails loudly.
    An unknown image ref falls back to the probe.
    """
    cached = getattr(context, "has_custom_command_list", None)
    if cached is not None:
        return cached
    stdout, returncode = run_ssh(context, "gsettings get org.gnome.shell enabled-extensions")
    if returncode != 0:
        context.has_custom_command_list = True
    else:
        context.has_custom_command_list = (
            "custom-command-list@storageb.github.com" in (stdout or "")
        )
    return context.has_custom_command_list


def before_all(context):
    userdata = context.config.userdata
    # Detect image family from BASE_IMAGE before IMAGE; composed runs replace
    # IMAGE with a run-scoped testsuite ref that carries no family (#907).
    image_ref = image_under_test(userdata)
    context.is_bluefin_image = _is_bluefin_image(image_ref) if image_ref else True
    context.is_dakota_image = _is_dakota_image(image_ref) if image_ref else False
    context.is_projectbluefin_image = _is_projectbluefin_image(image_ref)
    context.vm_ip = _first_value(
        userdata.get("vm_ip", ""),
        userdata.get("host", ""),
        os.environ.get("VM_IP", ""),
        os.environ.get("TMT_SSH_HOST", ""),
    )
    context.ssh_user = _first_value(
        userdata.get("vm_user", ""),
        userdata.get("user", ""),
        os.environ.get("VM_USER", ""),
        os.environ.get("SSH_USER", ""),
        os.environ.get("TMT_SSH_USER", "bluefin-test"),
    )
    context.ssh_key = _first_value(
        userdata.get("ssh_key", ""),
        userdata.get("key", ""),
        os.environ.get("SSH_KEY", ""),
        os.environ.get("SSH_KEY_PATH", ""),
        os.environ.get("TMT_SSH_KEY", "/etc/ssh/test-key/id_ed25519"),
    )
    session_env = _first_value(
        userdata.get("session_env", ""),
        os.environ.get("COMMON_SESSION_ENV_FILE", ""),
    )
    session_prefix = ""
    if session_env:
        quoted = shlex.quote(session_env)
        session_prefix = f"if [ -f {quoted} ]; then . {quoted}; fi; "
    # Set up Homebrew PATH so brew-installed tools (bat, eza, fd, rg, etc.) are
    # accessible in non-interactive SSH sessions.
    brew_prefix = (
        'export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH; '
        '[ -x /home/linuxbrew/.linuxbrew/bin/brew ] '
        '&& eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv 2>/dev/null)" '
        '|| true; '
    )
    context.ssh_command_prefix = (
        session_prefix
        + brew_prefix
        + 'XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}; '
        + 'export XDG_RUNTIME_DIR; '
        + 'SESSION_BUS=$(systemctl --user show-environment 2>/dev/null '
        + '| sed -n "s/^DBUS_SESSION_BUS_ADDRESS=//p" | head -1); '
        + '[ -z "$SESSION_BUS" ] && [ -S "$XDG_RUNTIME_DIR/bus" ] '
        + '&& SESSION_BUS="unix:path=$XDG_RUNTIME_DIR/bus"; '
        + '[ -n "$SESSION_BUS" ] && export DBUS_SESSION_BUS_ADDRESS="$SESSION_BUS"; '
        + 'WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-$(ls "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null '
        + '| head -1 | xargs -r basename 2>/dev/null || true)}; '
        + '[ -n "$WAYLAND_DISPLAY" ] && export WAYLAND_DISPLAY="$WAYLAND_DISPLAY"'
    )
    context.ssh_port = _first_value(
        userdata.get("ssh_port", ""),
        os.environ.get("SSH_PORT", ""),
        os.environ.get("VM_PORT", ""),
        os.environ.get("TMT_SSH_PORT", ""),
    ) or None
    context.command_stdout = ""
    context.last_command_output = ""
    context.last_ssh_result = None
    context.ssh_rc = 0
    context.has_brew = None


def before_scenario(context, scenario):
    from tests.shared.quarantine import skip_quarantine

    if skip_quarantine(scenario):
        return
    scenario_tags = _scenario_tags(scenario)
    # Skip @bluefin scenarios when running against a non-Bluefin image (e.g. Dakota).
    # Feature-level @bluefin tags are inherited by all scenarios in those features.
    is_bluefin = getattr(context, "is_bluefin_image", True)
    if not is_bluefin and "bluefin" in scenario_tags:
        scenario.skip(
            f"Skipping @bluefin scenario on non-Bluefin image "
            f"(IMAGE={os.environ.get('IMAGE', 'unknown')})"
        )
        return
    # Skip @dakota_only scenarios when running against a non-Dakota image.
    if not getattr(context, "is_dakota_image", False) and "dakota_only" in scenario_tags:
        scenario.skip(
            f"Skipping @dakota_only scenario on non-Dakota image "
            f"(IMAGE={os.environ.get('IMAGE', 'unknown')})"
        )
        return
    if "requires_brew" in scenario_tags and not _has_brew(context):
        scenario.skip("Homebrew not present on this image")
        return
    if "requires_toggle_action" in scenario_tags and not _has_toggle_action(context):
        scenario.skip("ujust toggle-updates ACTION support not present on this image")
        return
    if (
        "requires_custom_command_list" in scenario_tags
        and not getattr(context, "is_projectbluefin_image", False)
        and not _has_custom_command_list(context)
    ):
        scenario.skip("custom-command-list extension not enabled on this image")
        return
    feature_name = getattr(getattr(scenario, "feature", None), "name", "")
    if _is_container_target(context):
        if "portal" in feature_name.lower():
            scenario.skip("XDG desktop portals require full VM session")
            return
        if "read-only" in getattr(scenario, "name", "").lower():
            scenario.skip("Read-only /usr mount check requires booted ostree VM")
            return
    if "bootc unified storage" in getattr(scenario, "name", "").lower():
        out, _ = run_ssh(
            context,
            "systemctl show bootc-unified-storage.service --property=Result --value 2>/dev/null",
        )
        if out.strip() != "success":
            run_ssh(
                context,
                "sudo systemctl restart bootc-unified-storage.service --no-block 2>/dev/null || true",
            )
    if "podman user socket" in getattr(scenario, "name", "").lower():
        user = getattr(context, "ssh_user", None) or os.environ.get("SSH_USER", "bluefin-test")
        run_ssh(
            context,
            f"sudo loginctl enable-linger {shlex.quote(user)} 2>/dev/null || true; "
            "systemctl --user start podman.socket 2>/dev/null || true",
        )
    context.command_stdout = ""
    context.last_command_output = ""
    context.last_ssh_result = None
    context.ssh_rc = 0
    record_start(context)


def after_scenario(context, scenario):
    record_end(context, scenario)
