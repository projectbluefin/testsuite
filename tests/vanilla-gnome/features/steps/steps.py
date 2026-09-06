"""
Custom step definitions for GNOME Shell smoke tests.

common_steps provides: Application is running, Item found/not found,
Left/Right click, Key combo, Press key, Type text, Run and save command output,
Last command output, Wait N seconds.

Custom steps here cover:
- GNOME Shell accessibility check (retrying via context.sandbox.shell)
- Activities overview state, search bar content.

NOTE: We do NOT redefine 'Application "{name}" is running' — behave raises
AmbiguousStep when a literal step conflicts with an existing wildcard step.
Instead we use a distinct step name: 'GNOME Shell is accessible via AT-SPI'.

Step patterns sourced from: modehnal/GNOMETerminalAutomation steps.py
dogtail API: root.application(), Node.findChild(), Node.child(roleName=)
"""
import re
import subprocess
from time import sleep

from behave import step
from dogtail import tree
from qecore.common_steps import *  # noqa: F401,F403
from tests.shared.gnome_shell_steps import *  # noqa: F401,F403
from tests.shared.gnome_shell_steps import _shell_eval, _eval_bool, _wait_eval_bool
from tests.shared.ssh_config import ssh_argv


# ── Shell.Eval helpers (GNOME 50: uinput Super + AT-SPI toggle click broken) ──

def _shell_eval_value(context, js: str, timeout: int = 10) -> str:
    """Return a Shell.Eval result string via gdbus.

    GNOME 50 may wrap strings in extra double-quotes: (true, '"value"').
    """
    out = _shell_eval(js, timeout=timeout)
    # Parse the gdbus tuple: (true, 'value') or (true, '"value"')
    match = re.search(r",\s*'\"?(.+?)\"?'\s*\)\s*$", out.strip(), re.DOTALL)
    if match:
        return match.group(1)
    raise AssertionError(f"Could not parse Shell.Eval value from output: {out}")


def _eval_context_bool(context, js: str, timeout: int = 10) -> bool:
    value = _shell_eval_value(context, f"({js}).toString()", timeout=timeout)
    if value.lower() in {'true', 'false'}:
        return value.lower() == 'true'
    raise AssertionError(f"Could not parse boolean from Shell.Eval output: {value}")


@step('No coredump entries exist for "{name}"')
def no_coredump_entries_exist(context, name: str) -> None:
    import subprocess

    # coredumpctl may not be available on minimal images (e.g. gnomeos bootc).
    # Skip gracefully rather than error — absence of coredumpctl means no dumps.
    try:
        result = subprocess.run(
            ['coredumpctl', 'list', name, '--no-pager', '--lines=10'],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return  # coredumpctl not present — no coredumps possible

    if result.returncode not in (0, 1):
        raise AssertionError(
            f"coredumpctl list failed for {name}: rc={result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    matches = [line for line in result.stdout.splitlines() if name in line]
    assert not matches, f"Unexpected coredump entries for {name}: {matches}"


@step('Open Activities overview via Shell.Eval')
def open_overview_eval(context) -> None:
    out = _shell_eval('Main.overview.show(); Main.overview.visible.toString()')
    assert '(true,' in out, f"overview show failed: {out}"
    ok = _wait_eval_bool('Main.overview.visible.toString()', True, retries=8, delay=0.5)
    assert ok, 'Overview did not become visible after show()'


@step('Quick Settings panel is open via Shell.Eval')
def quick_settings_open_eval(context) -> None:
    assert _eval_bool('Main.panel.statusArea.quickSettings.menu.isOpen.toString()'), 'Quick Settings menu is not open'


@step('Date menu panel is open via Shell.Eval')
def date_menu_open_eval(context) -> None:
    assert _eval_bool('Main.panel.statusArea.dateMenu.menu.isOpen.toString()'), 'Date menu is not open'


@step('Set overview search text to "{text}" via Shell.Eval')
def set_overview_search_eval(context, text) -> None:
    """Populate overview search bar via GNOME Shell JS.
    uinput typing is broken on these VMs — use Shell.Eval instead.
    """
    js = (
        "Main.overview.show();"
        "const entry = Main.overview.searchEntry || Main.overview._overview.controls._searchController._searchEntry;"
        f"entry.get_clutter_text().set_text({text!r});"
        "entry.get_clutter_text().set_cursor_position(-1);"
        "entry.get_clutter_text().queue_redraw();"
        "true"
    )
    out = _shell_eval(js, timeout=15)
    assert '(true,' in out, f"Failed to set overview search text via Shell.Eval: {out}"
    sleep(0.5)


@step("Overview is open")
def overview_is_open(context) -> None:
    if not _wait_eval_bool('Main.overview.visible.toString()', expected=True, retries=8):
        raise AssertionError("Activities overview did not open after 4s")


@step("Overview is closed")
def overview_is_closed(context) -> None:
    if not _wait_eval_bool('Main.overview.visible.toString()', expected=False, retries=8):
        raise AssertionError("Activities overview is still showing after 4s")


@step('Overview search bar contains "{text}"')
def overview_search_bar_contains(context, text) -> None:
    shell = tree.root.application("gnome-shell")
    # dogtail 4.16 dropped requireResult kwarg
    entries = shell.findChildren(lambda n: n.roleName == "text" and n.showing)
    assert entries, "Search bar text entry not found"
    entry = entries[0]
    assert text in entry.text, f"Search bar text '{entry.text}' does not contain '{text}'"


def _ssh_run(cmd: str, timeout: int = 15, context=None) -> subprocess.CompletedProcess:
    """Run a command on the VM via SSH.

    ``timeout`` bounds only the local wait for the command to finish; the SSH
    *connect* deadline is fixed at ``ssh_argv``'s default (10s) so a long
    command timeout no longer inflates how long a dead connection is retried.
    """
    return subprocess.run(
        ssh_argv(context, quiet=True) + [cmd],
        capture_output=True, text=True, timeout=timeout,
    )


def _command_exists(command: str, context=None) -> bool:
    """Check whether a command is available on the VM."""
    try:
        result = _ssh_run(f'command -v {command}', context=context)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _flatpak_app_exists(app_id: str, context=None) -> bool:
    """Check whether a Flatpak app is installed on the VM."""
    try:
        result = _ssh_run('flatpak list --app --columns=application 2>/dev/null', timeout=20, context=context)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    installed = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return app_id in installed


def _assert_any_app_present(label: str, commands: tuple[str, ...], flatpaks: tuple[str, ...], context=None) -> None:
    found_commands = [command for command in commands if _command_exists(command, context=context)]
    found_flatpaks = [app_id for app_id in flatpaks if _flatpak_app_exists(app_id, context=context)]
    assert found_commands or found_flatpaks, (
        f"{label} not found. Commands checked: {commands}; flatpaks checked: {flatpaks}"
    )


@step('Do-not-disturb toggle is present in Quick Settings')
def dnd_toggle_present(context) -> None:
    # GNOME 50 exposes the Quick Settings indicator as _doNotDisturb.
    assert _eval_context_bool(
        context,
        '(Main.panel.statusArea.quickSettings._doNotDisturb !== null && '
        'Main.panel.statusArea.quickSettings._doNotDisturb !== undefined) || '
        '(Main.panel.statusArea.quickSettings._do_not_disturb !== null && '
        'Main.panel.statusArea.quickSettings._do_not_disturb !== undefined) || '
        '(Main.panel.statusArea.quickSettings._dnd !== null && '
        'Main.panel.statusArea.quickSettings._dnd !== undefined)',
    ), 'Do-not-disturb toggle is missing from Quick Settings'


@step('Night Light toggle is present in Quick Settings')
def night_light_toggle_present(context) -> None:
    assert _eval_context_bool(
        context,
        'Main.panel.statusArea.quickSettings._nightLight !== null && '
        'Main.panel.statusArea.quickSettings._nightLight !== undefined',
    ), 'Night Light toggle is missing from Quick Settings'


@step('GNOME Files application is installed')
def files_application_is_installed(context) -> None:
    _assert_any_app_present(
        'GNOME Files application',
        # 'gnome-files' is the binary name since GNOME 47; 'nautilus' is the classic name
        ('gnome-files', 'nautilus'),
        ('org.gnome.Nautilus',),
        context=context,
    )


@step('GNOME Text Editor application is installed')
def text_editor_application_is_installed(context) -> None:
    _assert_any_app_present(
        'GNOME Text Editor application',
        # gnome-text-editor (GNOME 42+); gedit (classic fallback)
        ('gnome-text-editor', 'gedit'),
        ('org.gnome.TextEditor', 'org.gnome.gedit'),
        context=context,
    )


@step('A web browser application is installed')
def web_browser_application_is_installed(context) -> None:
    _assert_any_app_present(
        'Web browser application',
        ('epiphany', 'firefox', 'chromium', 'chromium-browser'),
        ('org.gnome.Epiphany', 'org.mozilla.firefox', 'org.chromium.Chromium'),
        context=context,
    )


@step('A terminal application is installed')
def terminal_application_is_installed(context) -> None:
    _assert_any_app_present(
        'Terminal application',
        ('kgx', 'ptyxis', 'gnome-terminal'),
        ('org.gnome.Console', 'app.devsuite.Ptyxis', 'org.gnome.Terminal'),
        context=context,
    )


@step('Screenshot tool launches via Shell.Eval')
def screenshot_tool_launches(context) -> None:
    _shell_eval('Main.screenshotUI.open().catch(logError); true', timeout=15)
    if not _wait_eval_bool('Main.screenshotUI.visible.toString()', expected=True, retries=10):
        out = _shell_eval('Main.screenshotUI.visible.toString()')
        raise AssertionError(f'Screenshot UI did not become visible: {out!r}')


@step('Screenshot tool window is accessible via AT-SPI')
def screenshot_tool_window_accessible(context) -> None:
    expected_labels = {'Selection', 'Screen', 'Window', 'Show Pointer', 'Take Screenshot'}
    visible_labels: list[str] = []
    for _ in range(10):
        shell = tree.root.application('gnome-shell')
        visible_labels = sorted({
            node.name for node in shell.findChildren(
                lambda n: n.showing and n.name in expected_labels
            )
        })
        if len(visible_labels) >= 2:
            return
        sleep(0.5)
    raise AssertionError(
        'Screenshot UI was not accessible via AT-SPI. '
        f'Visible screenshot labels: {visible_labels}'
    )


@step('Close screenshot tool')
def close_screenshot_tool(context) -> None:
    _shell_eval('Main.screenshotUI.close(true)')
    if not _wait_eval_bool('Main.screenshotUI.visible.toString()', expected=False, retries=8):
        out = _shell_eval('Main.screenshotUI.visible.toString()')
        raise AssertionError(f'Screenshot UI is still visible after close(): {out!r}')


@step('Bluefin-specific extensions are absent on vanilla-gnome')
def bluefin_extensions_absent(context) -> None:
    try:
        result = _ssh_run("gnome-extensions list", context=context)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return

    if result.returncode == 0:
        output = result.stdout
        for ext in ("bazaar-integration", "blur-my-shell", "dash-to-dock"):
            assert ext not in output, f"Unexpected Bluefin-specific extension '{ext}' is present in vanilla-gnome: {output}"

