"""Common lifecycle steps parameterized by the canonical extension collection."""
import re
import json

from behave import step

from tests.shared.extension_session import ExtensionSession


@step('Hive extension "{profile}" is installed')
def installed_extension(context, profile):
    if profile not in context.extensions_collection:
        raise AssertionError(f"Unknown extension profile: {profile}")
    context.extension = ExtensionSession(context.extensions_collection[profile])
    context.extension.ensure_installed()


@step('I enable the selected Hive extension')
def enable_extension(context):
    context.extension.enable()


@step('I disable the selected Hive extension')
def disable_extension(context):
    context.extension.disable()


@step('the selected Hive extension is active')
def active_extension(context):
    assert context.extension.is_enabled(), f"Extension {context.extension.uuid} is not enabled"
    info = context.extension.command(["gnome-extensions", "info", context.extension.uuid]).stdout
    assert re.search(r"^\s*State:\s*(?:ACTIVE|ENABLED)\s*$", info, re.MULTILINE), info


@step('the selected Hive extension is inactive')
def inactive_extension(context):
    assert not context.extension.is_enabled(), f"Extension {context.extension.uuid} remains enabled"


# The Shell's preferences service (js/dbusServices/extensions/main.js) is a
# bare D-Bus service with no Gtk.Application, so its windows can carry no GTK
# application id; its Wayland app id (Mutter's WM class) is the service name.
_PREFS_WINDOW = (
    "(window.get_gtk_application_id() === 'org.gnome.Shell.Extensions' || "
    "window.get_wm_class() === 'org.gnome.Shell.Extensions' || "
    "window.get_wm_class_instance() === 'org.gnome.Shell.Extensions')"
)


def _close_new_preferences(session, previous):
    prior = json.dumps(previous)
    session.shell_json("(() => { const prior = " + prior + "; "
                       "for (const actor of global.get_window_actors()) { "
                       "const window = actor.get_meta_window(); "
                       "if (window && !prior.includes(window.get_stable_sequence()) && "
                       + _PREFS_WINDOW + ") "
                       "window.delete(global.display.get_current_time_roundtrip()); } return true; })()")
    session.wait_for(
        "global.get_window_actors().map(actor => actor.get_meta_window()).every(window => "
        "!" + _PREFS_WINDOW + " || " + prior + ".includes(window.get_stable_sequence()))"
    )


@step('the selected Hive extension preferences window is accessible')
def preferences_window(context):
    from dogtail import tree
    import time

    previous = context.extension.shell_json(
        "global.get_window_actors().map(actor => actor.get_meta_window().get_stable_sequence())"
    )
    context.extension_cleanups.append((_close_new_preferences, (context.extension, previous)))
    context.extension.command(["gnome-extensions", "prefs", context.extension.uuid])
    deadline = time.monotonic() + 15
    new_titles, seen = [], {}
    while time.monotonic() < deadline:
        new_titles = context.extension.shell_json(
            "global.get_window_actors().map(actor => actor.get_meta_window()).filter(window => "
            + _PREFS_WINDOW + " && !" +
            json.dumps(previous) + ".includes(window.get_stable_sequence())).map(window => window.get_title())"
        )
        seen = {}
        for app in tree.root.applications():
            frames = [(node.roleName, node.name, node.showing) for node in app.children
                      if node.roleName in ("frame", "dialog", "window")]
            seen[app.name] = frames
            if app.name not in ("org.gnome.Shell.Extensions", "gnome-extensions-prefs"):
                continue
            windows = app.findChildren(lambda node: node.roleName in ("frame", "dialog") and
                                      node.showing and node.name in new_titles)
            if windows:
                # Cleanup closes only new windows belonging to the preferences service.
                return
        time.sleep(0.1)
    # Say what each side saw, so a naming mismatch reads differently from a
    # window that never opened or an application missing from AT-SPI.
    shell_windows = context.extension.shell_json(
        "global.get_window_actors().map(actor => actor.get_meta_window()).map(window => ({"
        "title: window.get_title(), app: window.get_gtk_application_id(), "
        "wm_class: window.get_wm_class(), x11: window.get_client_type() === 1, "
        "new: !" + json.dumps(previous) + ".includes(window.get_stable_sequence())}))"
    )
    raise AssertionError(
        f"No accessible preferences window for {context.extension.uuid}; "
        f"new Shell titles {new_titles!r}; Shell windows {shell_windows!r}; "
        f"AT-SPI applications and top-level children {seen!r}"
    )
