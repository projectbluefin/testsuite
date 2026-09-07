"""
Common layer test environment — plain SSH, no qecore.

This suite validates the projectbluefin/common OCI layer by running CLI- and
GSettings-focused checks over SSH against a live Bluefin session.
"""
import os
import shlex

from tests.shared.ssh_steps import *  # noqa: F401,F403
from tests.shared.ssh_steps import run_ssh

try:
    from tests.shared.timing import record_end, record_start
except Exception:  # noqa: BLE001
    def record_start(context):
        return None

    def record_end(context, scenario):
        return None


def _first_value(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def _is_bluefin_image(image: str) -> bool:
    """Return True if the image reference looks like a Bluefin image.

    Matches the image name component only (e.g. "bluefin" in
    "ghcr.io/projectbluefin/bluefin:testing") to avoid false-positives where
    the org name "projectbluefin" would match a dakota image URL.
    """
    lower = image.lower()
    # Extract image name: last path segment before any tag/digest
    name = lower.split("/")[-1].split(":")[0].split("@")[0]
    return "bluefin" in name or "bazzite" in lower


def _is_dakota_image(image: str) -> bool:
    """Return True if the image reference looks like a Dakota image.

    Matches the image name component only (e.g. "dakota" in
    "ghcr.io/projectbluefin/dakota:testing") to avoid false-positives where
    the org name "projectbluefin" would match a Bluefin image URL.
    """
    lower = image.lower()
    name = lower.split("/")[-1].split(":")[0].split("@")[0]
    return "dakota" in name


def _scenario_tags(scenario) -> set[str]:
    return set(getattr(scenario, "effective_tags", scenario.tags))


def _has_brew(context) -> bool:
    cached = getattr(context, "has_brew", None)
    if cached is not None:
        return cached
    _, returncode = run_ssh(context, "test -x /home/linuxbrew/.linuxbrew/bin/brew")
    context.has_brew = returncode == 0
    return context.has_brew


def _has_bctl(context) -> bool:
    """Return True when bluefinctl (`bctl`) is installed on the VM.

    bluefinctl ships via the Homebrew preinstall set, and brew-setup.service is
    masked in QEMU CI, so `bctl` is absent there. Scenarios tagged
    ``@requires_bctl`` skip with an explicit reason rather than failing on a
    missing binary.
    """
    cached = getattr(context, "has_bctl", None)
    if cached is not None:
        return cached
    _, returncode = run_ssh(context, "command -v bctl")
    context.has_bctl = returncode == 0
    return context.has_bctl


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


def before_all(context):
    userdata = context.config.userdata
    # When IMAGE env var is set (GHA runner), auto-detect image family so
    # @bluefin scenarios can be skipped gracefully on non-Bluefin images.
    image_ref = os.environ.get("IMAGE", userdata.get("image", ""))
    context.is_bluefin_image = _is_bluefin_image(image_ref) if image_ref else True
    context.is_dakota_image = _is_dakota_image(image_ref) if image_ref else False
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
    context.has_bctl = None


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
    if "requires_bctl" in scenario_tags and not _has_bctl(context):
        scenario.skip("bluefinctl (bctl) not present on this image")
        return
    if "requires_toggle_action" in scenario_tags and not _has_toggle_action(context):
        scenario.skip("ujust toggle-updates ACTION support not present on this image")
        return
    if "bootc unified storage" in getattr(scenario, "name", "").lower():
        out, _ = run_ssh(
            context,
            "systemctl show bootc-unified-storage.service --property=Result --value 2>/dev/null",
        )
        if out.strip() != "success":
            run_ssh(
                context,
                "sudo systemctl restart bootc-unified-storage.service 2>/dev/null || true",
            )
    context.command_stdout = ""
    context.last_command_output = ""
    context.last_ssh_result = None
    context.ssh_rc = 0
    record_start(context)


def _cleanup_devmode(context, scenario) -> None:
    """Restore devmode to inactive after a @devmode_cleanup scenario.

    The devmode mutation scenario changes durable system state (group
    membership), so teardown must not live in trailing scenario steps: a
    failure part-way through would leak an enabled devmode into the next run
    or retry. Skipped scenarios never mutated anything, so they are ignored.
    """
    if "devmode_cleanup" not in _scenario_tags(scenario):
        return
    status = getattr(scenario, "status", None)
    if getattr(status, "name", status) == "skipped":
        return
    try:
        run_ssh(context, "bctl devmode --disable")
    except Exception:  # noqa: BLE001 - teardown must never mask the real failure
        pass


def after_scenario(context, scenario):
    _cleanup_devmode(context, scenario)
    record_end(context, scenario)
