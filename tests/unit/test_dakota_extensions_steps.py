"""Unit tests for Dakota extension step helpers in gnome_extensions_steps."""

from unittest.mock import MagicMock, patch
import pytest

from tests.smoke.features.steps import gnome_extensions_steps as ges


class TestGnomeExtensionIsInstalled:
    def test_passes_when_in_gnome_extensions_list(self):
        context = MagicMock()
        with patch.object(ges, "_run_host", return_value=("ext-a@local\next-b@local\n", 0, "")):
            ges.gnome_extension_is_installed(context, "ext-a@local")

    def test_passes_when_in_gdbus_list(self):
        context = MagicMock()
        calls = [
            ("other@local\n", 1, "failed"),
            ("({'ext-b@local': <{'state': <1.0>}>},)", 0, ""),
        ]
        with patch.object(ges, "_run_host", side_effect=calls):
            ges.gnome_extension_is_installed(context, "ext-b@local")

    def test_passes_when_in_filesystem(self):
        context = MagicMock()
        calls = [
            ("other@local\n", 1, "failed"),
            ("", 1, "failed"),
            ("", 0, ""),
        ]
        with patch.object(ges, "_run_host", side_effect=calls):
            ges.gnome_extension_is_installed(context, "ext-c@local")

    def test_fails_when_nowhere_to_be_found(self):
        context = MagicMock()
        calls = [
            ("other@local\n", 0, ""),
            ("", 1, "failed"),
            ("", 1, "not found"),
        ]
        with patch.object(ges, "_run_host", side_effect=calls):
            with pytest.raises(AssertionError, match="is not installed"):
                ges.gnome_extension_is_installed(context, "missing@local")


class TestDconfPathHasValue:
    def test_passes_when_value_matches(self):
        context = MagicMock()
        with patch.object(ges, "_run_host", return_value=("'ublue-logo-symbolic'\n", 0, "")):
            ges.dconf_path_has_value(
                context,
                "/org/gnome/shell/extensions/custom-command-list/menuicon-setting",
                "'ublue-logo-symbolic'",
            )

    def test_raises_when_value_mismatches(self):
        context = MagicMock()
        with patch.object(ges, "_run_host", return_value=("'other-icon'\n", 0, "")):
            with pytest.raises(AssertionError, match="mismatch"):
                ges.dconf_path_has_value(
                    context,
                    "/org/gnome/shell/extensions/custom-command-list/menuicon-setting",
                    "'ublue-logo-symbolic'",
                )

    def test_raises_when_dconf_fails(self):
        context = MagicMock()
        with patch.object(ges, "_run_host", return_value=("", 1, "error reading dconf")):
            with pytest.raises(AssertionError, match="failed"):
                ges.dconf_path_has_value(
                    context,
                    "/org/gnome/shell/extensions/custom-command-list/menuicon-setting",
                    "'ublue-logo-symbolic'",
                )
