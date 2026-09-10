"""Unit tests for Copyous stress and crash-regression step helpers."""

import sys
import types
from unittest.mock import MagicMock, patch
import pytest


def _import_module():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    dogtail_stub = types.ModuleType("dogtail")
    tree_stub = types.ModuleType("dogtail.tree")
    tree_stub.root = MagicMock()
    sys.modules["dogtail"] = dogtail_stub
    sys.modules["dogtail.tree"] = tree_stub

    steps_pkg_stub = types.ModuleType("steps")
    steps_pkg_stub.__path__ = []
    sys.modules["steps"] = steps_pkg_stub

    gnome_extensions_stub = types.ModuleType("steps.gnome_extensions_steps")
    gnome_extensions_stub._extension_state = MagicMock(return_value="1")
    gnome_extensions_stub._run_host = MagicMock(return_value=("", 0, ""))
    sys.modules["steps.gnome_extensions_steps"] = gnome_extensions_stub

    steps_mod_stub = types.ModuleType("steps.steps")
    steps_mod_stub._eval_bool = MagicMock(return_value=True)
    steps_mod_stub._shell_eval = MagicMock(return_value="")
    sys.modules["steps.steps"] = steps_mod_stub

    import tests.smoke.features.steps.copyous_stress_steps as m
    return m


class TestSnapshottingState:
    def test_captures_marker_and_rss(self):
        css = _import_module()
        context = MagicMock()
        with patch.object(css, "_journal_snapshot_marker", return_value="2026-09-10 02:00:00"), \
             patch.object(css, "_gnome_shell_rss_kb", return_value=150000):
            css.snapshotting_gnome_shell_state_and_journal_marker(context)
            assert context.copyous_baseline_marker == "2026-09-10 02:00:00"
            assert context.copyous_baseline_rss_kb == 150000


class TestClipboardChurn:
    def test_generates_churn_and_retains_final(self):
        css = _import_module()
        context = MagicMock()
        copied = []

        def fake_copy(val):
            copied.append(val)

        with patch.object(css, "_clipboard_set", side_effect=fake_copy), \
             patch.object(css, "sleep"):
            css.generating_rapid_clipboard_churn(context, 10)
            assert len(copied) == 10
            assert context.last_copied_payload == copied[-1]

    def test_retains_final_copied_payload_asserts_equality(self):
        css = _import_module()
        context = MagicMock()
        context.last_copied_payload = "target-string"
        with patch.object(css, "_clipboard_get", return_value="target-string"):
            css.clipboard_retains_final_copied_payload(context)

    def test_retains_final_copied_payload_raises_on_mismatch(self):
        css = _import_module()
        context = MagicMock()
        context.last_copied_payload = "target-string"
        with patch.object(css, "_clipboard_get", return_value="different-string"):
            with pytest.raises(AssertionError, match="mismatch"):
                css.clipboard_retains_final_copied_payload(context)


class TestMemoryCeiling:
    def test_memory_growth_passes_within_limit(self):
        css = _import_module()
        context = MagicMock()
        context.copyous_baseline_rss_kb = 100000  # ~100MB
        with patch.object(css, "_gnome_shell_rss_kb", return_value=150000):  # +50MB
            css.gnome_shell_memory_growth_remains_strictly_bounded(context, 200)

    def test_memory_growth_fails_when_exceeding_limit(self):
        css = _import_module()
        context = MagicMock()
        context.copyous_baseline_rss_kb = 100000  # ~100MB
        # 350000 - 100000 = 250MB growth, limit 200MB
        with patch.object(css, "_gnome_shell_rss_kb", return_value=350000):
            with pytest.raises(AssertionError, match="exceeding safety ceiling"):
                css.gnome_shell_memory_growth_remains_strictly_bounded(context, 200)


class TestHeavyPayloads:
    def test_1mb_payload(self):
        css = _import_module()
        context = MagicMock()
        with patch.object(css, "_clipboard_set") as mock_set, \
             patch.object(css, "sleep"):
            css.copying_one_megabyte_payload(context)
            assert len(context.last_copied_payload) == 1024 * 1024
            mock_set.assert_called_once()

    def test_multiline_payload(self):
        css = _import_module()
        context = MagicMock()
        with patch.object(css, "_clipboard_set") as mock_set, \
             patch.object(css, "sleep"):
            css.copying_multiline_text_payload(context, 100)
            assert len(context.last_copied_payload.splitlines()) == 100
            mock_set.assert_called_once()

    def test_null_bytes_and_sql(self):
        css = _import_module()
        context = MagicMock()
        with patch.object(css, "_clipboard_set"), patch.object(css, "sleep"):
            css.copying_payload_with_null_and_escapes(context)
            assert "\x00" in context.last_copied_payload

            css.copying_empty_string_payload(context)
            assert context.last_copied_payload == ""

            css.copying_payload_with_sql_injection(context)
            assert "DROP TABLE" in context.last_copied_payload


class TestShellResponsiveness:
    def test_passes_when_shell_eval_returns_true(self):
        css = _import_module()
        context = MagicMock()
        with patch.object(css, "_eval_bool", return_value=True):
            css.gnome_shell_remains_responsive(context, 2)

    def test_raises_when_shell_eval_never_responds(self):
        css = _import_module()
        context = MagicMock()
        with patch.object(css, "_eval_bool", side_effect=Exception("deadlock")), \
             patch.object(css, "sleep"):
            with pytest.raises(AssertionError, match="did not respond"):
                css.gnome_shell_remains_responsive(context, 1)
