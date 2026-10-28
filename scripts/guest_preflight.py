#!/usr/bin/env python3
"""Pre-boot inventory and provenance gate for the extension-validation lane.

The ``gnome-e2e`` action writes an OCI image to a raw disk with
``bootc install to-disk`` and then mounts the resulting ostree deployment to
configure it.  For ``suite: extensions`` (issue #908) this script inspects that
mounted deployment *before* the VM boots and:

* records guest provenance (image reference, resolved digest, ``os-release``
  identity such as GNOME OS ``IMAGE_VERSION`` / ``GNOMEOS_COMMIT``) so a run
  states exactly which guest it tested;
* fails closed, as an infrastructure error, when a prerequisite the lane needs
  is missing — most importantly ``gnome-ponytail-daemon``, which stock GNOME OS
  does not ship and which qecore-headless needs for virtual input.

Without this gate a missing prerequisite surfaces minutes later as a confusing
qecore/behave failure (or no results at all) instead of a named provisioning
error.  The final path component is checked with ``os.path.lexists`` and never
resolved, and a hit is discarded when any parent directory resolves outside the
guest tree, so an absolute symlink inside the guest is never followed onto the
host.

See ``docs/skills/ci-ops/e2e-workflow/references/gnome-extensions-validation.md``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

GNOME_OS_ID = "org.gnome.os"

# Each prerequisite is satisfied when ANY of its candidate patterns matches a
# path in the guest tree.  Patterns are relative to the deployment root and may
# contain glob wildcards.  Every entry maps to a concrete step of the gnome-e2e
# action: direct kernel boot, harness SSH/sudo provisioning, GDM autologin into
# a Wayland session, the in-guest pip install of the test stack, and the
# qecore-headless AT-SPI + virtual-input run.
REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "kernel": ("usr/lib/modules/*/vmlinuz",),
    "initramfs": ("usr/lib/modules/*/initramfs.img",),
    "sshd": ("usr/bin/sshd", "usr/sbin/sshd"),
    "sshd.service": ("usr/lib/systemd/system/sshd.service",),
    "sudo": ("usr/bin/sudo",),
    "gdm": ("usr/bin/gdm", "usr/sbin/gdm"),
    "gnome-shell": ("usr/bin/gnome-shell",),
    "gnome-extensions": ("usr/bin/gnome-extensions",),
    "gdbus": ("usr/bin/gdbus",),
    "python3": ("usr/bin/python3",),
    "python-ensurepip": (
        "usr/lib/python3*/ensurepip/__init__.py",
        "usr/lib64/python3*/ensurepip/__init__.py",
    ),
    "python-gi": (
        "usr/lib/python3*/site-packages/gi/__init__.py",
        "usr/lib64/python3*/site-packages/gi/__init__.py",
    ),
    "at-spi-bus-launcher": ("usr/libexec/at-spi-bus-launcher",),
    "uinput": (
        "usr/lib/modules/*/kernel/drivers/input/misc/uinput.ko*",
        # built-in rather than a module: listed in modules.builtin instead
        "usr/lib/modules/*/modules.builtin",
    ),
    "gnome-ponytail-daemon": (
        "usr/libexec/gnome-ponytail-daemon",
        "usr/bin/gnome-ponytail-daemon",
    ),
}

OS_RELEASE_KEYS = (
    "NAME",
    "ID",
    "VERSION_ID",
    "PRETTY_NAME",
    "IMAGE_VERSION",
    "GNOMEOS_COMMIT",
)


def _has_builtin_uinput(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(line.rstrip().endswith("/uinput.ko") for line in text.splitlines())


def _parents_inside(root: Path, rel: Path) -> bool:
    """True when every parent directory of *rel* resolves inside *root*.

    ``lexists`` and ``Path.glob`` both traverse symlinked parent directories, so
    a guest ``usr/lib64 -> /usr/lib`` would otherwise be probed on the host.
    """
    base = root.resolve()
    return all((root / parent).resolve().is_relative_to(base) for parent in rel.parents)


def _matches(root: Path, pattern: str) -> list[str]:
    """Return guest-relative paths matching *pattern*, without following links."""
    if not any(ch in pattern for ch in "*?["):
        hit = os.path.lexists(root / pattern) and _parents_inside(root, Path(pattern))
        return [pattern] if hit else []
    found = []
    for path in sorted(root.glob(pattern)):
        if not _parents_inside(root, path.relative_to(root)):
            continue
        if pattern.endswith("modules.builtin") and not _has_builtin_uinput(path):
            continue
        found.append(path.relative_to(root).as_posix())
    return found


def check_requirements(root: Path) -> dict[str, list[str]]:
    """Map each prerequisite name to the guest paths that satisfy it (empty = missing)."""
    result: dict[str, list[str]] = {}
    for name, patterns in REQUIREMENTS.items():
        hits: list[str] = []
        for pattern in patterns:
            hits.extend(_matches(root, pattern))
        result[name] = hits
    return result


def parse_os_release(text: str) -> dict[str, str]:
    """Parse os-release(5) ``KEY=value`` lines, unquoting values."""
    data: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        data[key.strip()] = value
    return data


def read_os_release(root: Path) -> dict[str, str]:
    """Read the guest's os-release, preferring /usr/lib (etc/ is a symlink on GNOME OS)."""
    for rel in ("usr/lib/os-release", "etc/os-release"):
        path = root / rel
        if path.is_file() and not path.is_symlink():
            return parse_os_release(path.read_text(encoding="utf-8", errors="replace"))
    return {}


def build_report(
    root: Path, image_ref: str = "", image_digest: str = ""
) -> dict[str, Any]:
    """Build the provenance + prerequisite report for the guest tree at *root*."""
    os_release = read_os_release(root)
    found = check_requirements(root)
    missing = [name for name, hits in found.items() if not hits]
    return {
        "image_ref": image_ref,
        "image_digest": image_digest,
        "os_release": {k: os_release[k] for k in OS_RELEASE_KEYS if k in os_release},
        "is_gnome_os": os_release.get("ID") == GNOME_OS_ID,
        "requirements": found,
        "missing": missing,
        "ok": bool(os_release) and not missing,
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"image:  {report['image_ref'] or '(not given)'}",
        f"digest: {report['image_digest'] or '(not given)'}",
    ]
    osr = report["os_release"]
    if osr:
        lines.append(
            "guest:  "
            + " ".join(f"{k}={v}" for k, v in osr.items() if k != "PRETTY_NAME")
        )
    else:
        lines.append("guest:  os-release not found")
    lines.append(f"GNOME OS: {'yes' if report['is_gnome_os'] else 'no'}")
    for name, hits in report["requirements"].items():
        lines.append(f"  {'ok     ' if hits else 'MISSING'} {name}" + (f"  ({hits[0]})" if hits else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path, help="mounted guest deployment root")
    parser.add_argument("--image-ref", default="", help="image reference that was installed")
    parser.add_argument("--image-digest", default="", help="resolved manifest digest of that image")
    parser.add_argument("--output", type=Path, help="write the JSON report here")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"::error::guest root {args.root} is not a directory", file=sys.stderr)
        return 2

    report = build_report(args.root, args.image_ref, args.image_digest)
    print(format_report(report))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not report["os_release"]:
        print("::error::guest has no os-release; cannot record provenance. Failing closed.")
        return 1
    if report["missing"]:
        print(
            "::error::guest image lacks extension-validation prerequisites: "
            + ", ".join(report["missing"])
            + ". This is a provisioning error, not a test result. Failing closed."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
