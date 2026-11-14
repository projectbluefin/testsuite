"""Unit tests for gnome_text_editor_steps.py and gnome_files_steps.py helper functions."""
import sys
import types
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _make_base_stubs():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    dogtail_stub = types.ModuleType("dogtail")
    tree_stub = types.ModuleType("dogtail.tree")
    tree_stub.root = MagicMock()
    sys.modules["dogtail"] = dogtail_stub
    sys.modules["dogtail.tree"] = tree_stub

    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    app_support_stub = types.ModuleType("app_support")
    app_support_stub.launch_background = MagicMock()
    app_support_stub._IN_CONTAINER = False
    app_support_stub._ssh_args = MagicMock(return_value=[])
    app_support_stub.atspi_click = MagicMock()
    from tests.shared import app_support as shared_app_support  # noqa: PLC0415
    app_support_stub.describe_subtree = shared_app_support.describe_subtree
    app_support_stub.newest_active_frame = shared_app_support.newest_active_frame
    app_support_stub.node_text = shared_app_support.node_text
    app_support_stub.stop_app_instances = MagicMock()
    sys.modules["app_support"] = app_support_stub


def _import_text_editor_steps():
    _make_base_stubs()
    for key in list(sys.modules):
        if "gnome_text_editor_steps" in key:
            del sys.modules[key]
    import tests.smoke.features.steps.gnome_text_editor_steps as m  # noqa: PLC0415
    return m


def _import_files_steps():
    _make_base_stubs()
    for key in list(sys.modules):
        if "gnome_files_steps" in key:
            del sys.modules[key]
    import tests.smoke.features.steps.gnome_files_steps as m  # noqa: PLC0415
    return m


# ===========================================================================
# gnome_text_editor_steps.py
# ===========================================================================

class TestTextEditorConstants:
    def test_app_names_is_tuple(self):
        m = _import_text_editor_steps()
        assert isinstance(m.TEXT_EDITOR_APP_NAMES, tuple)
        assert "gnome-text-editor" in m.TEXT_EDITOR_APP_NAMES

    def test_text_widget_roles_is_set(self):
        m = _import_text_editor_steps()
        assert isinstance(m.TEXT_WIDGET_ROLES, set)
        assert "text" in m.TEXT_WIDGET_ROLES

    def test_dialog_entry_roles_is_set(self):
        m = _import_text_editor_steps()
        assert isinstance(m.DIALOG_ENTRY_ROLES, set)
        assert "entry" in m.DIALOG_ENTRY_ROLES

    def test_button_roles_is_set(self):
        m = _import_text_editor_steps()
        assert isinstance(m.BUTTON_ROLES, set)
        assert "push button" in m.BUTTON_ROLES


class TestNodeText:
    def test_returns_name_when_only_name_present(self):
        m = _import_text_editor_steps()
        node = MagicMock()
        node.name = "  Hello  "
        node.text = ""
        assert m._node_text(node) == "Hello"

    def test_returns_text_when_only_text_present(self):
        m = _import_text_editor_steps()
        node = MagicMock()
        node.name = ""
        node.text = "  World  "
        assert m._node_text(node) == "World"

    def test_combines_name_and_text_when_different(self):
        m = _import_text_editor_steps()
        node = MagicMock()
        node.name = "Title"
        node.text = "Body"
        result = m._node_text(node)
        assert "Title" in result
        assert "Body" in result

    def test_does_not_duplicate_when_name_equals_text(self):
        m = _import_text_editor_steps()
        node = MagicMock()
        node.name = "Same"
        node.text = "Same"
        result = m._node_text(node)
        assert result.count("Same") == 1

    def test_returns_empty_string_when_both_empty(self):
        m = _import_text_editor_steps()
        node = MagicMock()
        node.name = ""
        node.text = ""
        assert m._node_text(node) == ""

    def test_tolerates_text_attribute_exception(self):
        m = _import_text_editor_steps()
        node = MagicMock()
        node.name = "Only Name"
        type(node).text = property(lambda self: (_ for _ in ()).throw(RuntimeError("no text")))
        result = m._node_text(node)
        assert result == "Only Name"

    def test_handles_none_name(self):
        m = _import_text_editor_steps()
        node = MagicMock()
        node.name = None
        node.text = "Content"
        assert m._node_text(node) == "Content"


class TestVisibleDialogText:
    def test_returns_list_of_visible_text(self):
        m = _import_text_editor_steps()

        def fake_find(pred):
            n1, n2 = MagicMock(), MagicMock()
            n1.showing = True
            n1.name = "Save"
            n1.text = ""
            n2.showing = True
            n2.name = "Cancel"
            n2.text = ""
            return [n for n in [n1, n2] if pred(n)]

        dialog = MagicMock()
        dialog.findChildren = MagicMock(side_effect=fake_find)
        result = m._visible_dialog_text(dialog)
        assert "Save" in result
        assert "Cancel" in result

    def test_deduplicates_text(self):
        m = _import_text_editor_steps()
        n = MagicMock()
        n.showing = True
        n.name = "Duplicate"
        n.text = "Duplicate"
        dialog = MagicMock()
        dialog.findChildren.return_value = [n, n]
        result = m._visible_dialog_text(dialog)
        assert result.count("Duplicate") == 1

    def test_returns_empty_list_when_no_visible_text(self):
        m = _import_text_editor_steps()
        dialog = MagicMock()
        dialog.findChildren.return_value = []
        assert m._visible_dialog_text(dialog) == []


# ===========================================================================
# gnome_files_steps.py
# ===========================================================================

class TestFilesConstants:
    def test_files_app_names_is_tuple(self):
        m = _import_files_steps()
        assert isinstance(m.FILES_APP_NAMES, tuple)
        assert "org.gnome.Nautilus" in m.FILES_APP_NAMES
        assert "nautilus" in m.FILES_APP_NAMES

    def test_files_sidebar_uris_is_dict(self):
        m = _import_files_steps()
        assert isinstance(m.FILES_SIDEBAR_URIS, dict)
        assert "Home" in m.FILES_SIDEBAR_URIS
        assert m.FILES_SIDEBAR_URIS["Home"] == "home:///"

    def test_files_sidebar_uris_trash_entry(self):
        m = _import_files_steps()
        assert m.FILES_SIDEBAR_URIS.get("Trash") == "trash:///"

    def test_files_sidebar_uris_has_standard_locations(self):
        m = _import_files_steps()
        for location in ("Downloads", "Documents", "Desktop", "Music", "Pictures", "Videos"):
            assert location in m.FILES_SIDEBAR_URIS, f"{location!r} missing from FILES_SIDEBAR_URIS"

    def test_files_launch_targets_is_tuple(self):
        m = _import_files_steps()
        assert isinstance(m.FILES_LAUNCH_TARGETS, tuple)
        assert len(m.FILES_LAUNCH_TARGETS) >= 1

    def test_files_launch_targets_has_desktop_file(self):
        m = _import_files_steps()
        all_values = [v for _, v in m.FILES_LAUNCH_TARGETS]
        assert any("Nautilus" in v or "nautilus" in v for v in all_values)


class TestFilesSkipIfNoAtspi:
    def test_returns_false_when_tree_available(self):
        m = _import_files_steps()
        context = MagicMock()
        result = m._skip_if_no_atspi(context)
        assert result is False

    def test_returns_true_when_tree_is_none(self):
        m = _import_files_steps()
        m.tree = None
        context = MagicMock()
        result = m._skip_if_no_atspi(context)
        assert result is True

    def test_calls_scenario_skip_with_atspi_message(self):
        m = _import_files_steps()
        m.tree = None
        context = MagicMock()
        m._skip_if_no_atspi(context)
        context.scenario.skip.assert_called_once()
        assert "AT-SPI" in context.scenario.skip.call_args[0][0]
