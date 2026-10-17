"""Re-export of tests/shared/app_support.py for the smoke step modules.

The launch and AT-SPI helpers live in tests/shared so suites other than smoke
can use them: CI copies only tests/<suite> and tests/shared into the VM, so a
suite that imports from tests/smoke fails to load there. Smoke step modules keep
importing ``app_support`` from their own steps directory through this file.
"""

from tests.shared.app_support import (  # noqa: F401
    _IN_CONTAINER,
    _ssh_args,
    _ssh_launch,
    _ssh_run,
    atspi_click,
    launch_background,
    launch_target_available,
)
