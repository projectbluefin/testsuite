"""Image-family selection for variant-tagged behave scenarios."""
import os

_BLUEFIN_FAMILY_NAMES = ("bluefin", "bazzite", "utah", "common")


def image_name(image: str) -> str:
    """Return the image-name component, excluding registry, org, tag, and digest."""
    return image.lower().split("/")[-1].split(":")[0].split("@")[0]


def image_under_test(userdata=None) -> str:
    """Return the input image, not a composed run-scoped testsuite image.

    Precedence is BASE_IMAGE, then IMAGE, then ``-D image=`` (userdata), as
    the common suite has always resolved it. This differs from the software
    suite, which checks ``-D image=`` before IMAGE.
    """
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


def is_utah_image(image: str) -> bool:
    return "utah" in image_name(image)


def composefs_backend_from_markers(ostree_prepare_root_present: bool) -> bool:
    """Return True when an image installs with the composefs backend.

    bootc selects the backend from the image's install config, which is
    unchanged at runtime. It ships exactly one backend marker per image:
      * ostree backend   -> /usr/lib/ostree/prepare-root.conf   (always present)
      * composefs backend -> /usr/lib/composefs/setup-root.toml (no ostree marker)
    The ostree marker is the reliable discriminator: composefs images never
    ship ``prepare-root.conf``, so its absence selects the composefs backend.
    We key on the ostree marker rather than betting on the composefs marker's
    exact path (which varies across bootc versions). Any image that ships
    ``prepare-root.conf`` installs with the ostree backend.
    """
    return not ostree_prepare_root_present


def is_composefs_image(
    image: str,
    *,
    ostree_prepare_root_present: bool = False,
) -> bool:
    """Return True when ``image`` should install with the composefs backend.

    The backend is a property of the image, not its name, so the marker is
    supplied by the caller (a runtime ``podman run`` probe of the image in
    ``e2e.yml``). Kept mutually exclusive with the ostree path: an ostree image
    ships ``prepare-root.conf`` (``ostree_prepare_root_present`` is True), so
    the predicate is False regardless of any composefs marker.
    """
    return composefs_backend_from_markers(ostree_prepare_root_present)
