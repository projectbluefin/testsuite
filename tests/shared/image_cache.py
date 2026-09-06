"""Runtime gate for scenarios that need a pre-cached OCI image on the DUT.

Scenarios tagged ``@requires_cached_image`` pull no image themselves: they
assume the image they name is already in the device-under-test's local podman
store.  When it is not, a live registry pull would run inside the scenario and
blow the CI timeout instead of reporting a useful result, so the scenario is
skipped with an explicit reason.

This is the same "skip until the capability exists, then activate
automatically" contract as ``@requires_bctl`` and ``@requires_toggle_action``
in ``tests/common/features/environment.py``.  It is deliberately NOT a
non-runnable tag: it does not belong in ``tests/shared/quarantine.py`` or in
the CI tag filters, because the scenario must run the moment the image is
cached — no feature-file edit required.

The images a scenario needs are read from its own step text rather than from a
constant here, so the feature file stays the single source of truth for which
image is under test.
"""

from __future__ import annotations

import re
import shlex
import subprocess


REQUIRES_CACHED_IMAGE_TAG = "requires_cached_image"

# Quoted arguments in a behave step name, e.g. the "…fedora-toolbox:latest" in
#   * DX distrobox "test-box" can be created from "registry.fedoraproject.org/fedora-toolbox:latest"
_QUOTED = re.compile(r'"([^"]*)"')


def _looks_like_image_ref(token: str) -> bool:
    """Return True when ``token`` is an OCI image reference.

    Deliberately strict so ordinary quoted step arguments (container names,
    package names, absolute paths like ``/usr/bin/htop``) are never mistaken
    for images:

    * a registry host — the segment before the first ``/`` must contain a dot
      or a port, or be ``localhost``;
    * a tag or digest on the final path segment.

    Bare references such as ``fedora:latest`` are rejected: without an explicit
    registry, what ``podman image exists`` resolves depends on the DUT's
    ``registries.conf`` search list, so the probe could disagree with the pull
    the scenario would perform.
    """
    if not token or any(char.isspace() for char in token):
        return False
    registry, _, remainder = token.partition("/")
    if not remainder:
        return False
    if "." not in registry and ":" not in registry and registry != "localhost":
        return False
    final_segment = remainder.rsplit("/", 1)[-1]
    return ":" in final_segment or "@" in final_segment


def images_required_by(scenario) -> list[str]:
    """Return the image references named in ``scenario``'s steps, in order.

    Duplicates are collapsed: several steps in one scenario normally name the
    same image, and probing it once is enough.
    """
    images: list[str] = []
    for step in getattr(scenario, "steps", []) or []:
        for token in _QUOTED.findall(getattr(step, "name", "") or ""):
            if _looks_like_image_ref(token) and token not in images:
                images.append(token)
    return images


def _ssh_returncode(context, command: str, timeout: int) -> int:
    """Run ``command`` on the DUT over SSH and return its exit status.

    This deliberately does NOT reuse ``run_ssh`` from
    ``tests/shared/ssh_steps.py``. Importing that module registers its ``@step``
    phrases into behave's global registry, and several of them
    (``SSH command return code is "{code}"``,
    ``Last command output contains "{text}"``) are also defined by
    ``tests/dx/features/steps/steps.py``. Importing it from a DX
    ``before_scenario`` hook would raise ``AmbiguousStep`` and take down the
    whole suite. ``tests/shared/ssh_config.py`` is the connection-detail helper
    that carries no step definitions, which is exactly what a hook needs.

    Unlike a step, this probe leaves ``context`` untouched: it runs before the
    per-scenario state reset and must not smear command output across scenarios.
    """
    from tests.shared.ssh_config import ssh_argv

    argv = ssh_argv(context, quiet=True) + [command]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).returncode


def image_is_cached(context, image: str, timeout: int = 30) -> bool:
    """Return True when ``image`` is already in the DUT's local podman store.

    ``podman image exists`` exits 0 for a locally present image and 1
    otherwise, and never contacts a registry — which is the whole point: the
    probe itself must not be able to trigger the pull it is guarding against.
    """
    try:
        returncode = _ssh_returncode(
            context, f"podman image exists {shlex.quote(image)}", timeout
        )
    except (subprocess.TimeoutExpired, OSError):
        # An unreachable DUT is not evidence that the image is cached.
        return False
    return returncode == 0


def _skip(scenario, reason: str) -> None:
    """Skip ``scenario``, tolerating behave versions whose skip() takes no reason."""
    try:
        scenario.skip(reason)
    except TypeError:
        scenario.skip()


def skip_when_image_not_cached(context, scenario) -> bool:
    """Skip ``scenario`` unless every image it names is cached on the DUT.

    Returns True when the scenario was skipped, so ``before_scenario`` hooks
    can mirror the ``skip_quarantine`` call shape::

        if skip_when_image_not_cached(context, scenario):
            return
    """
    tags = set(getattr(scenario, "effective_tags", scenario.tags))
    if REQUIRES_CACHED_IMAGE_TAG not in tags:
        return False

    images = images_required_by(scenario)
    if not images:
        # Authoring error, not an environment condition: the tag promises an
        # image the steps never name.  tests/unit/test_image_cache.py fails on
        # this against the real feature files, so it cannot reach CI silently.
        _skip(
            scenario,
            f"@{REQUIRES_CACHED_IMAGE_TAG} — no image reference found in the "
            "scenario's steps; tag it on a scenario that names its image",
        )
        return True

    missing = [image for image in images if not image_is_cached(context, image)]
    if missing:
        _skip(
            scenario,
            f"@{REQUIRES_CACHED_IMAGE_TAG} — not in the DUT's local podman "
            f"store: {', '.join(missing)}",
        )
        return True
    return False
