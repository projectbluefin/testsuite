"""Unit tests for tests/shared/image_family.py (#1073)."""
import importlib
from types import SimpleNamespace

import pytest

from tests.shared.image_family import (
    image_name,
    image_under_test,
    is_bluefin_image,
    is_dakota_image,
)


@pytest.fixture(autouse=True)
def _clear_image_env(monkeypatch):
    monkeypatch.delenv("BASE_IMAGE", raising=False)
    monkeypatch.delenv("IMAGE", raising=False)


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/projectbluefin/bluefin:testing",
        "ghcr.io/projectbluefin/bluefin-lts@sha256:abc",
        "ghcr.io/ublue-os/bazzite:stable",
        "ghcr.io/projectbluefin/utah@sha256:abc",
        "ghcr.io/projectbluefin/common:e2e-pr-12-abc",
    ],
)
def test_common_layer_consumers_select_bluefin_scenarios(image):
    assert is_bluefin_image(image)
    assert not is_dakota_image(image)


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/projectbluefin/dakota:testing",
        "ghcr.io/common/dakota:testing",
        "ghcr.io/utah/dakota@sha256:abc",
    ],
)
def test_org_name_never_selects_a_family(image):
    assert is_dakota_image(image)
    assert not is_bluefin_image(image)


def test_image_name_strips_registry_org_tag_and_digest():
    assert image_name("GHCR.io/ProjectBluefin/Utah:testing@sha256:abc") == "utah"


def test_composed_run_uses_base_image_family(monkeypatch):
    monkeypatch.setenv("BASE_IMAGE", "ghcr.io/projectbluefin/dakota:testing")
    monkeypatch.setenv("IMAGE", "ghcr.io/projectbluefin/testsuite-e2e:run-1")

    image = image_under_test({"image": "ghcr.io/projectbluefin/bluefin:testing"})

    assert image == "ghcr.io/projectbluefin/dakota:testing"


def test_image_then_userdata_are_fallbacks(monkeypatch):
    assert image_under_test({"image": "ghcr.io/projectbluefin/utah:testing"}) == (
        "ghcr.io/projectbluefin/utah:testing"
    )
    monkeypatch.setenv("IMAGE", "ghcr.io/projectbluefin/bluefin:testing")
    assert image_under_test({"image": "ghcr.io/projectbluefin/utah:testing"}) == (
        "ghcr.io/projectbluefin/bluefin:testing"
    )
    assert image_under_test() == "ghcr.io/projectbluefin/bluefin:testing"


def _smoke_detect(userdata):
    from tests.unit.test_smoke_environment import _setup_stubs

    _setup_stubs()
    env = importlib.import_module("tests.smoke.features.environment")
    context = SimpleNamespace(config=SimpleNamespace(userdata=userdata))
    env._detect_image_family(context)
    return context


def test_smoke_composed_run_keeps_dakota_family(monkeypatch):
    monkeypatch.setenv("BASE_IMAGE", "ghcr.io/projectbluefin/dakota:testing")
    monkeypatch.setenv("IMAGE", "ghcr.io/projectbluefin/testsuite-e2e:run-1")

    context = _smoke_detect({})

    assert context.is_dakota_image is True
    assert context.is_bluefin_image is False


def test_smoke_reads_image_from_behave_userdata(monkeypatch):
    context = _smoke_detect({"image": "ghcr.io/projectbluefin/utah@sha256:abc"})

    assert context.is_bluefin_image is True
    assert context.is_dakota_image is False


def test_smoke_defaults_to_bluefin_when_no_image_is_known():
    context = _smoke_detect({})

    assert context.is_bluefin_image is True
    assert context.is_dakota_image is False
