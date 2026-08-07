"""Runtime environment detection shared across suites.

Container lanes (Argo ``run-container-tests``) execute behave *inside* the
nested target container itself, so there is no separate device under test and
no sshd to reach. VM lanes (KubeVirt) run behave on a runner that talks to the
device under test over SSH.

Scenarios that can only be meaningful against a real VM — anything driving the
device over SSH, or asserting on boot-time/kernel state a container never has —
must be tagged ``@vm_only`` and are skipped by the suite hooks in a container
lane.
"""

import os

# Podman writes /run/.containerenv into every container it starts, including
# the nested systemd target used by container lanes. A KubeVirt VM never has
# it. This is a stronger signal than probing for /usr/bin/bootc, which is
# present in the container lane too because the target *is* a bootc image.
CONTAINER_MARKER = "/run/.containerenv"


def in_container_lane() -> bool:
    """Return True when behave is running inside a container-lane target."""
    return os.path.exists(CONTAINER_MARKER)
