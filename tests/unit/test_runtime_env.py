"""Unit tests for tests/shared/runtime_env.py container-lane detection."""

from unittest.mock import patch

from tests.shared import runtime_env


class TestInContainerLane:
    def test_true_when_containerenv_present(self):
        with patch("os.path.exists", side_effect=lambda p: p == runtime_env.CONTAINER_MARKER):
            assert runtime_env.in_container_lane() is True

    def test_false_when_containerenv_absent(self):
        with patch("os.path.exists", return_value=False):
            assert runtime_env.in_container_lane() is False

    def test_checks_the_podman_marker_path(self):
        assert runtime_env.CONTAINER_MARKER == "/run/.containerenv"
