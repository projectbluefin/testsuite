from tests.shared.image_family import image_under_test, is_bluefin_image, is_dakota_image


def test_common_layer_consumers_select_bluefin_scenarios():
    assert is_bluefin_image("ghcr.io/projectbluefin/utah@sha256:abc")
    assert is_bluefin_image("ghcr.io/projectbluefin/common:e2e-pr-12-abc")
    assert not is_bluefin_image("ghcr.io/projectbluefin/dakota:testing")
    assert not is_bluefin_image("ghcr.io/common/dakota:testing")


def test_composed_run_uses_base_image_family(monkeypatch):
    monkeypatch.setenv("BASE_IMAGE", "ghcr.io/projectbluefin/dakota:testing")
    monkeypatch.setenv("IMAGE", "ghcr.io/projectbluefin/testsuite-e2e:run-1")

    image = image_under_test()

    assert is_dakota_image(image)
    assert not is_bluefin_image(image)
