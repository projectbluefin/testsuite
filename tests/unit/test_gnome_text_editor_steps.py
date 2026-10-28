"""Unit tests for tests/smoke/features/steps/gnome_text_editor_steps.py."""

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_text_editor_steps(tree_available: bool = True):
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    dogtail_stub = types.ModuleType("dogtail")
    tree_stub = types.ModuleType("dogtail.tree")
    if tree_available:
        tree_stub.root = MagicMock()
    sys.modules["dogtail"] = dogtail_stub
    sys.modules["dogtail.tree"] = tree_stub

    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    app_support_stub = types.ModuleType("app_support")
    app_support_stub.launch_background = MagicMock(return_value="command")
    sys.modules["app_support"] = app_support_stub

    for key in list(sys.modules):
        if "gnome_text_editor_steps" in key:
            del sys.modules[key]

    import tests.smoke.features.steps.gnome_text_editor_steps as m  # noqa: PLC0415
    return m


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestTextEditorConstants:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def test_app_names_is_tuple(self):
        assert isinstance(self.m.TEXT_EDITOR_APP_NAMES, tuple)

    def test_app_names_contains_gnome_text_editor(self):
        assert "gnome-text-editor" in self.m.TEXT_EDITOR_APP_NAMES

    def test_launch_targets_is_tuple(self):
        assert isinstance(self.m.TEXT_EDITOR_LAUNCH_TARGETS, tuple)

    def test_launch_targets_contains_desktop_entry(self):
        targets = [t for pair in self.m.TEXT_EDITOR_LAUNCH_TARGETS for t in pair]
        assert "org.gnome.TextEditor.desktop" in targets

    def test_text_widget_roles_is_set(self):
        assert isinstance(self.m.TEXT_WIDGET_ROLES, set)

    def test_text_widget_roles_contains_text(self):
        assert "text" in self.m.TEXT_WIDGET_ROLES

    def test_text_widget_roles_contains_entry(self):
        assert "entry" in self.m.TEXT_WIDGET_ROLES

    def test_dialog_entry_roles_is_set(self):
        assert isinstance(self.m.DIALOG_ENTRY_ROLES, set)

    def test_button_roles_is_set(self):
        assert isinstance(self.m.BUTTON_ROLES, set)

    def test_button_roles_contains_push_button(self):
        assert "push button" in self.m.BUTTON_ROLES


# ---------------------------------------------------------------------------
# _skip_if_no_atspi
# ---------------------------------------------------------------------------

class TestSkipIfNoAtspi:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def test_returns_true_and_skips_when_tree_is_none(self):
        context = MagicMock()
        with patch.object(self.m, "tree", None):
            result = self.m._skip_if_no_atspi(context)
        assert result is True
        context.scenario.skip.assert_called_once_with(
            "AT-SPI unavailable: dogtail not imported in this environment"
        )

    def test_returns_false_when_tree_is_available(self):
        context = MagicMock()
        with patch.object(self.m, "tree", MagicMock()):
            result = self.m._skip_if_no_atspi(context)
        assert result is False
        context.scenario.skip.assert_not_called()

    def test_does_not_raise_when_skip_raises(self):
        context = MagicMock()
        context.scenario.skip.side_effect = RuntimeError("skip not available")
        with patch.object(self.m, "tree", None):
            result = self.m._skip_if_no_atspi(context)
        assert result is True


# ---------------------------------------------------------------------------
# _text_editor_app
# ---------------------------------------------------------------------------

class TestTextEditorApp:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def test_returns_first_matching_app(self):
        mock_app = MagicMock()
        tree_mock = MagicMock()
        tree_mock.root.application.return_value = mock_app
        with patch.object(self.m, "tree", tree_mock):
            result = self.m._text_editor_app()
        assert result is mock_app

    def test_tries_next_name_when_first_raises(self):
        mock_app = MagicMock()
        call_count = {"n": 0}

        def side_effect(name):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("not found")
            return mock_app

        tree_mock = MagicMock()
        tree_mock.root.application.side_effect = side_effect
        with patch.object(self.m, "tree", tree_mock):
            result = self.m._text_editor_app()
        assert result is mock_app
        assert call_count["n"] == 2

    def test_raises_assertion_error_when_all_names_fail(self):
        tree_mock = MagicMock()
        tree_mock.root.application.side_effect = RuntimeError("not found")
        with patch.object(self.m, "tree", tree_mock):
            with pytest.raises(AssertionError, match="GNOME Text Editor application was not found"):
                self.m._text_editor_app()


# ---------------------------------------------------------------------------
# _node_text
# ---------------------------------------------------------------------------

class TestNodeText:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def test_returns_name_when_present(self):
        node = MagicMock()
        node.name = "  Hello  "
        node.text = ""
        assert self.m._node_text(node) == "Hello"

    def test_falls_back_to_text_when_name_is_blank(self):
        node = MagicMock()
        node.name = "   "
        node.text = "  World  "
        assert self.m._node_text(node) == "World"

    def test_returns_empty_string_when_both_blank(self):
        node = MagicMock()
        node.name = ""
        node.text = ""
        assert self.m._node_text(node) == ""

    def test_combines_name_and_text_when_both_non_empty(self):
        node = MagicMock()
        node.name = "Title"
        node.text = "Body"
        result = self.m._node_text(node)
        assert "Title" in result
        assert "Body" in result

    def test_does_not_duplicate_value_when_name_equals_text(self):
        node = MagicMock()
        node.name = "Same"
        node.text = "Same"
        result = self.m._node_text(node)
        assert result.count("Same") == 1

    def test_handles_text_attribute_exception(self):
        node = MagicMock()
        node.name = "Name"
        type(node).text = property(lambda self: (_ for _ in ()).throw(RuntimeError("no text")))
        result = self.m._node_text(node)
        assert result == "Name"

    def test_returns_empty_string_when_name_missing(self):
        node = object()
        assert self.m._node_text(node) == ""


# ---------------------------------------------------------------------------
# _text_editor_window
# ---------------------------------------------------------------------------

class TestTextEditorWindow:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def test_returns_first_visible_frame(self):
        frame = MagicMock()
        frame.roleName = "frame"
        frame.showing = True
        app_mock = MagicMock()

        def find(pred):
            return [frame] if pred(frame) else []

        app_mock.findChildren.side_effect = find
        with patch.object(self.m, "_text_editor_app", return_value=app_mock):
            result = self.m._text_editor_window()
        assert result is frame

    def test_raises_when_no_visible_frame(self):
        app_mock = MagicMock()
        app_mock.findChildren.return_value = []
        with patch.object(self.m, "_text_editor_app", return_value=app_mock):
            with pytest.raises(AssertionError, match="Visible GNOME Text Editor window not found"):
                self.m._text_editor_window()


# ---------------------------------------------------------------------------
# _buffer_text
# ---------------------------------------------------------------------------

class TestBufferText:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def _make_area(self, name="", text="", children=None):
        area = MagicMock()
        area.name = name
        area.text = text
        area.showing = True
        area.roleName = "text"

        child_nodes = children or []

        def find(pred):
            return [c for c in child_nodes if pred(c)]

        area.findChildren.side_effect = find
        return area

    def test_returns_direct_name_when_present(self):
        area = self._make_area(name="some text")
        result = self.m._buffer_text(area)
        assert "some text" in result

    def test_returns_empty_string_when_area_is_blank_and_no_children(self):
        area = self._make_area()
        result = self.m._buffer_text(area)
        assert result == ""

    def test_includes_child_node_text(self):
        child = MagicMock()
        child.name = "child content"
        child.text = ""
        child.showing = True
        child.roleName = "text"
        child.findChildren.return_value = []
        area = self._make_area(children=[child])
        result = self.m._buffer_text(area)
        assert "child content" in result

    def test_deduplicates_repeated_text(self):
        area = self._make_area(name="hello")
        child = MagicMock()
        child.name = "hello"
        child.text = ""
        child.showing = True
        child.roleName = "text"

        def find(pred):
            return [child] if pred(child) else []

        area.findChildren.side_effect = find
        result = self.m._buffer_text(area)
        assert result.count("hello") == 1


# ---------------------------------------------------------------------------
# _visible_dialog_text
# ---------------------------------------------------------------------------

class TestVisibleDialogText:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def test_returns_list_of_visible_text(self):
        node1 = MagicMock()
        node1.name = "Save As"
        node1.text = ""
        node1.showing = True
        node2 = MagicMock()
        node2.name = "Cancel"
        node2.text = ""
        node2.showing = True
        dialog = MagicMock()

        def find(pred):
            return [n for n in [node1, node2] if pred(n)]

        dialog.findChildren.side_effect = find
        result = self.m._visible_dialog_text(dialog)
        assert "Save As" in result
        assert "Cancel" in result

    def test_returns_empty_list_when_no_visible_nodes(self):
        dialog = MagicMock()
        dialog.findChildren.return_value = []
        result = self.m._visible_dialog_text(dialog)
        assert result == []

    def test_deduplicates_text(self):
        node = MagicMock()
        node.name = "duplicate"
        node.text = "duplicate"
        node.showing = True

        def find(pred):
            return [node] if pred(node) else []

        dialog = MagicMock()
        dialog.findChildren.side_effect = find
        result = self.m._visible_dialog_text(dialog)
        assert result.count("duplicate") == 1


# ---------------------------------------------------------------------------
# launch_text_editor_via_command
# ---------------------------------------------------------------------------

class TestLaunchTextEditorViaCommand:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def test_sets_launch_target_on_context(self):
        context = MagicMock()
        app_support = sys.modules["app_support"]
        app_support.launch_background.return_value = "command"
        with patch.object(self.m, "tree", MagicMock()), \
             patch("time.sleep"):
            self.m.launch_text_editor_via_command(context)
        assert context.text_editor_launch_target == "command"

    def test_skips_when_tree_unavailable(self):
        context = MagicMock()
        with patch.object(self.m, "tree", None):
            self.m.launch_text_editor_via_command(context)
        context.scenario.skip.assert_called_once()


# ---------------------------------------------------------------------------
# text_editor_is_no_longer_running
# ---------------------------------------------------------------------------

class TestTextEditorIsNoLongerRunning:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def test_passes_when_app_not_found(self):
        tree_mock = MagicMock()
        tree_mock.root.applications.return_value = []
        tree_mock.root.application.side_effect = RuntimeError("not found")
        with patch.object(self.m, "tree", tree_mock), \
             patch.object(self.m, "sleep") as sleep_mock:
            self.m.text_editor_is_no_longer_running(MagicMock())
        sleep_mock.assert_not_called()
        # tree.root.application(name) retries internally; a missing app must
        # not multiply the close wait through it (#1044).
        tree_mock.root.application.assert_not_called()

    def test_passes_when_app_has_no_visible_frames(self):
        app_mock = MagicMock()
        app_mock.name = "Text Editor"
        app_mock.findChildren.return_value = []
        tree_mock = MagicMock()
        tree_mock.root.applications.return_value = [app_mock]
        with patch.object(self.m, "tree", tree_mock), \
             patch.object(self.m, "sleep"):
            self.m.text_editor_is_no_longer_running(MagicMock())

    def test_raises_when_app_stays_visible(self):
        frame = MagicMock()
        frame.roleName = "frame"
        frame.showing = True
        app_mock = MagicMock()
        app_mock.name = "gnome-text-editor"

        def find(pred):
            return [frame] if pred(frame) else []

        app_mock.findChildren.side_effect = find
        tree_mock = MagicMock()
        tree_mock.root.applications.return_value = [app_mock]
        with patch.object(self.m, "tree", tree_mock), \
             patch.object(self.m, "sleep"):
            with pytest.raises(AssertionError, match="GNOME Text Editor is still visible"):
                self.m.text_editor_is_no_longer_running(MagicMock())
        tree_mock.root.application.assert_not_called()

    def test_snapshot_failure_counts_as_closed(self):
        tree_mock = MagicMock()
        tree_mock.root.applications.side_effect = RuntimeError("registry busy")
        with patch.object(self.m, "tree", tree_mock), \
             patch.object(self.m, "sleep"):
            self.m.text_editor_is_no_longer_running(MagicMock())
        tree_mock.root.application.assert_not_called()


# ---------------------------------------------------------------------------
# text_editor_buffer_contains
# ---------------------------------------------------------------------------

class TestTextEditorBufferContains:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def test_passes_when_expected_text_is_in_buffer(self):
        context = MagicMock()
        area = MagicMock()
        area.name = "Hello World"
        area.text = ""
        area.showing = True
        area.roleName = "text"
        area.findChildren.return_value = []
        area.focusable = True

        with patch.object(self.m, "_editable_text_area", return_value=area), \
             patch("time.sleep"):
            self.m.text_editor_buffer_contains(context, "Hello")
        assert context.text_editor_last_text == "Hello"

    def test_raises_when_expected_text_not_in_buffer(self):
        area = MagicMock()
        area.name = "some other text"
        area.text = ""
        area.showing = True
        area.roleName = "text"
        area.findChildren.return_value = []
        area.focusable = True

        with patch.object(self.m, "_editable_text_area", return_value=area), \
             patch("time.sleep"):
            with pytest.raises(AssertionError, match="Expected"):
                self.m.text_editor_buffer_contains(MagicMock(), "missing content")


# ---------------------------------------------------------------------------
# text_editor_creates_new_empty_document_buffer
# ---------------------------------------------------------------------------

class TestTextEditorCreatesNewEmptyDocumentBuffer:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def test_passes_when_buffer_is_empty_after_ctrl_n(self):
        context = MagicMock()
        context.text_editor_last_text = "old content"
        area = MagicMock()
        area.name = ""
        area.text = ""
        area.showing = True
        area.roleName = "text"
        area.findChildren.return_value = []
        area.focusable = True

        with patch.object(self.m, "_editable_text_area", return_value=area), \
             patch("time.sleep"):
            self.m.text_editor_creates_new_empty_document_buffer(context)

    def test_raises_when_buffer_still_has_old_content(self):
        context = MagicMock()
        context.text_editor_last_text = "hello"
        area = MagicMock()
        area.name = "hello"
        area.text = ""
        area.showing = True
        area.roleName = "text"
        area.findChildren.return_value = []
        area.focusable = True

        with patch.object(self.m, "_editable_text_area", return_value=area), \
             patch("time.sleep"):
            with pytest.raises(AssertionError, match="Expected a new empty Text Editor buffer"):
                self.m.text_editor_creates_new_empty_document_buffer(context)


# ---------------------------------------------------------------------------
# text_editor_save_dialog_is_open
# ---------------------------------------------------------------------------

class TestTextEditorSaveDialogIsOpen:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def _make_app_with_save_dialog(self):
        entry = MagicMock()
        entry.roleName = "entry"
        entry.showing = True
        entry.name = ""
        entry.text = ""

        dialog = MagicMock()
        dialog.roleName = "dialog"
        dialog.showing = True

        def dialog_find(pred):
            return [entry] if pred(entry) else []

        dialog.findChildren.side_effect = dialog_find

        app = MagicMock()

        def app_find(pred):
            return [dialog] if pred(dialog) else []

        app.findChildren.side_effect = app_find
        return app, dialog

    def test_sets_context_save_dialog_when_found(self):
        context = MagicMock()
        app, dialog = self._make_app_with_save_dialog()
        tree_mock = MagicMock()
        tree_mock.root.application.return_value = app
        with patch.object(self.m, "tree", tree_mock), \
             patch("time.sleep"):
            self.m.text_editor_save_dialog_is_open(context)
        assert context.text_editor_save_dialog is dialog

    def test_raises_when_no_save_dialog_found(self):
        app = MagicMock()
        app.findChildren.return_value = []
        tree_mock = MagicMock()
        tree_mock.root.application.return_value = app
        with patch.object(self.m, "tree", tree_mock), \
             patch("time.sleep"):
            with pytest.raises(AssertionError, match="save dialog was not found"):
                self.m.text_editor_save_dialog_is_open(MagicMock())

    def test_accepts_dialog_with_save_button_and_no_entry(self):
        context = MagicMock()
        save_btn = MagicMock()
        save_btn.roleName = "push button"
        save_btn.name = "Save"
        save_btn.showing = True

        dialog = MagicMock()
        dialog.roleName = "dialog"
        dialog.showing = True

        def dialog_find(pred):
            return [save_btn] if pred(save_btn) else []

        dialog.findChildren.side_effect = dialog_find

        app = MagicMock()

        def app_find(pred):
            return [dialog] if pred(dialog) else []

        app.findChildren.side_effect = app_find
        tree_mock = MagicMock()
        tree_mock.root.application.return_value = app
        with patch.object(self.m, "tree", tree_mock), \
             patch("time.sleep"):
            self.m.text_editor_save_dialog_is_open(context)
        assert context.text_editor_save_dialog is dialog


# ---------------------------------------------------------------------------
# text_editor_discard_dialog_is_open
# ---------------------------------------------------------------------------

class TestTextEditorDiscardDialogIsOpen:
    def setup_method(self):
        self.m = _import_text_editor_steps()

    def _make_app_with_discard_dialog(self):
        discard_btn = MagicMock()
        discard_btn.roleName = "push button"
        discard_btn.name = "Discard"
        discard_btn.showing = True

        dialog = MagicMock()
        dialog.roleName = "dialog"
        dialog.showing = True

        def dialog_find(pred):
            return [discard_btn] if pred(discard_btn) else []

        dialog.findChildren.side_effect = dialog_find

        app = MagicMock()

        def app_find(pred):
            return [dialog] if pred(dialog) else []

        app.findChildren.side_effect = app_find
        return app, dialog

    def test_sets_context_discard_dialog_when_found(self):
        context = MagicMock()
        app, dialog = self._make_app_with_discard_dialog()
        tree_mock = MagicMock()
        tree_mock.root.application.return_value = app
        with patch.object(self.m, "tree", tree_mock), \
             patch("time.sleep"):
            self.m.text_editor_discard_dialog_is_open(context)
        assert context.text_editor_discard_dialog is dialog

    def test_raises_when_no_discard_button_in_dialog(self):
        cancel_btn = MagicMock()
        cancel_btn.roleName = "push button"
        cancel_btn.name = "Cancel"
        cancel_btn.text = ""
        cancel_btn.showing = True

        dialog = MagicMock()
        dialog.roleName = "dialog"
        dialog.showing = True

        def dialog_find(pred):
            return [cancel_btn] if pred(cancel_btn) else []

        dialog.findChildren.side_effect = dialog_find

        app = MagicMock()

        def app_find(pred):
            return [dialog] if pred(dialog) else []

        app.findChildren.side_effect = app_find
        tree_mock = MagicMock()
        tree_mock.root.application.return_value = app
        with patch.object(self.m, "tree", tree_mock), \
             patch("time.sleep"):
            with pytest.raises(AssertionError, match="discard dialog"):
                self.m.text_editor_discard_dialog_is_open(MagicMock())

    def test_raises_when_no_dialogs_at_all(self):
        app = MagicMock()
        app.findChildren.return_value = []
        tree_mock = MagicMock()
        tree_mock.root.application.return_value = app
        with patch.object(self.m, "tree", tree_mock), \
             patch("time.sleep"):
            with pytest.raises(AssertionError, match="discard dialog"):
                self.m.text_editor_discard_dialog_is_open(MagicMock())

    def test_discard_check_is_case_insensitive(self):
        context = MagicMock()
        discard_btn = MagicMock()
        discard_btn.roleName = "button"
        discard_btn.name = "DISCARD"
        discard_btn.showing = True

        dialog = MagicMock()
        dialog.roleName = "dialog"
        dialog.showing = True

        def dialog_find(pred):
            return [discard_btn] if pred(discard_btn) else []

        dialog.findChildren.side_effect = dialog_find

        app = MagicMock()

        def app_find(pred):
            return [dialog] if pred(dialog) else []

        app.findChildren.side_effect = app_find
        tree_mock = MagicMock()
        tree_mock.root.application.return_value = app
        with patch.object(self.m, "tree", tree_mock), \
             patch("time.sleep"):
            self.m.text_editor_discard_dialog_is_open(context)
        assert context.text_editor_discard_dialog is dialog
