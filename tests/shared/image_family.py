"""Image-family selection for variant-tagged behave scenarios."""
import os

_BLUEFIN_FAMILY_NAMES = ("bluefin", "bazzite", "utah", "common")


def image_name(image: str) -> str:
    """Return the image-name component, excluding registry, org, tag, and digest."""
    return image.lower().split("/")[-1].split(":")[0].split("@")[0]


def image_under_test(userdata=None) -> str:
    """Return the input image, not a composed run-scoped testsuite image."""
    return (
        os.environ.get("BASE_IMAGE")
        or os.environ.get("IMAGE")
        or (userdata or {}).get("image", "")
    )


def is_bluefin_image(image: str) -> bool:
    """Return True for images that ship Bluefin's common desktop layer."""
    name = image_name(image)
    return any(family in name for family in _BLUEFIN_FAMILY_NAMES)


def is_dakota_image(image: str) -> bool:
    return "dakota" in image_name(image)
