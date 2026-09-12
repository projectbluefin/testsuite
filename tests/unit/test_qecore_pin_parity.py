"""Runner image and in-VM qecore installs must stay on the same version.

tests/smoke/features/environment.py monkeypatches qecore.utility internals
(_get_uinput_device, introduced in qecore 4.19). If the runner container and
the VM-side install drift, the patched keyboard hooks raise AttributeError,
the warning is swallowed, and every typed character silently vanishes —
scenarios then fail on downstream assertions (e.g. Firefox navigation).
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_CONTAINERFILE = REPO_ROOT / "container" / "Containerfile.runner"
GNOME_E2E_ACTION = REPO_ROOT / ".github" / "actions" / "gnome-e2e" / "action.yml"

PACKAGES = ("qecore", "behave", "dogtail", "python-uinput")


def _pin(text: str, package: str) -> str | None:
    match = re.search(rf"\b{re.escape(package)}==([0-9][^\s'\"\\]*)", text)
    return match.group(1) if match else None


class QecorePinParityTests(unittest.TestCase):
    def test_runner_and_vm_installs_pin_the_same_versions(self) -> None:
        runner = RUNNER_CONTAINERFILE.read_text(encoding="utf-8")
        vm = GNOME_E2E_ACTION.read_text(encoding="utf-8")
        for package in PACKAGES:
            with self.subTest(package=package):
                runner_pin = _pin(runner, package)
                vm_pin = _pin(vm, package)
                self.assertIsNotNone(
                    runner_pin, f"{package} must be pinned in {RUNNER_CONTAINERFILE.name}"
                )
                self.assertIsNotNone(
                    vm_pin,
                    f"{package} must be pinned in the in-VM install in {GNOME_E2E_ACTION.name}",
                )
                self.assertEqual(
                    runner_pin,
                    vm_pin,
                    f"{package} pin drift: runner={runner_pin} vm={vm_pin}",
                )


if __name__ == "__main__":
    unittest.main()
