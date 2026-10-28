"""Unit tests for :mod:`scripts.guest_preflight`.

The extension-validation lane (issue #908) must fail closed, before boot, when
the guest image lacks a prerequisite, and must record which guest it tested.
The fixture tree mirrors the layout of the official GNOME OS nightly bootc
image (inventoried from ``nightly.20261027.1``), which ships everything except
``gnome-ponytail-daemon``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.guest_preflight import (
    REQUIREMENTS,
    build_report,
    check_requirements,
    main,
    parse_os_release,
)

GNOME_OS_RELEASE = """\
NAME="GNOME OS"
VERSION="Nightly (Container Image)"
VERSION_ID="Nightly"
ID="org.gnome.os"
PRETTY_NAME="GNOME OS Nightly (Container Image)"
IMAGE_VERSION="nightly.20261027.1"
GNOMEOS_COMMIT="9c38eabcde1ed15f01f4250323ce6a8ab1b8a3da"
"""

# Paths observed in the GNOME OS nightly image, one per prerequisite.
GNOME_OS_PATHS = [
    "usr/lib/modules/7.3.0/vmlinuz",
    "usr/lib/modules/7.3.0/initramfs.img",
    "usr/lib/modules/7.3.0/kernel/drivers/input/misc/uinput.ko.zst",
    "usr/bin/sshd",
    "usr/lib/systemd/system/sshd.service",
    "usr/bin/sudo",
    "usr/bin/gdm",
    "usr/bin/gnome-shell",
    "usr/bin/gnome-extensions",
    "usr/bin/gdbus",
    "usr/bin/python3",
    "usr/lib/python3.14/ensurepip/__init__.py",
    "usr/lib/python3.14/site-packages/gi/__init__.py",
    "usr/libexec/at-spi-bus-launcher",
]


def _make_tree(root: Path, paths: list[str], os_release: str | None = GNOME_OS_RELEASE) -> Path:
    for rel in paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    if os_release is not None:
        (root / "usr/lib").mkdir(parents=True, exist_ok=True)
        (root / "usr/lib/os-release").write_text(os_release)
        (root / "etc").mkdir(exist_ok=True)
        os.symlink("../usr/lib/os-release", root / "etc/os-release")
    return root


@pytest.fixture
def stock_gnome_os(tmp_path: Path) -> Path:
    return _make_tree(tmp_path, GNOME_OS_PATHS)


@pytest.fixture
def gnome_os_with_ponytail(stock_gnome_os: Path) -> Path:
    (stock_gnome_os / "usr/libexec/gnome-ponytail-daemon").touch()
    return stock_gnome_os


def test_stock_gnome_os_is_missing_only_ponytail(stock_gnome_os: Path) -> None:
    report = build_report(stock_gnome_os)
    assert report["missing"] == ["gnome-ponytail-daemon"]
    assert report["ok"] is False
    assert report["is_gnome_os"] is True


def test_complete_guest_passes_and_records_provenance(gnome_os_with_ponytail: Path) -> None:
    report = build_report(
        gnome_os_with_ponytail,
        image_ref="quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-nightly",
        image_digest="sha256:abc",
    )
    assert report["ok"] is True
    assert report["missing"] == []
    assert report["image_digest"] == "sha256:abc"
    assert report["os_release"]["IMAGE_VERSION"] == "nightly.20261027.1"
    assert report["os_release"]["GNOMEOS_COMMIT"] == "9c38eabcde1ed15f01f4250323ce6a8ab1b8a3da"
    assert "VERSION" not in report["os_release"]  # only the provenance keys


def test_non_gnome_os_guest_is_recorded_not_relabelled(tmp_path: Path) -> None:
    root = _make_tree(
        tmp_path,
        GNOME_OS_PATHS + ["usr/libexec/gnome-ponytail-daemon"],
        os_release='NAME="Dakota"\nID=dakota\n',
    )
    report = build_report(root)
    assert report["ok"] is True
    assert report["is_gnome_os"] is False


@pytest.mark.parametrize("name", sorted(REQUIREMENTS))
def test_each_requirement_fails_closed_when_absent(tmp_path: Path, name: str) -> None:
    full = GNOME_OS_PATHS + ["usr/libexec/gnome-ponytail-daemon"]
    root = _make_tree(tmp_path, full)
    for pattern in REQUIREMENTS[name]:
        for hit in sorted(root.glob(pattern)):
            hit.unlink()
    assert name in build_report(root)["missing"]


def test_builtin_uinput_satisfies_requirement(tmp_path: Path) -> None:
    paths = [p for p in GNOME_OS_PATHS if "uinput" not in p]
    root = _make_tree(tmp_path, paths)
    builtin = root / "usr/lib/modules/7.3.0/modules.builtin"
    builtin.write_text("kernel/drivers/input/misc/uinput.ko\n")
    assert check_requirements(root)["uinput"] == ["usr/lib/modules/7.3.0/modules.builtin"]


def test_lib64_ensurepip_satisfies_requirement(tmp_path: Path) -> None:
    lib64 = "usr/lib64/python3.14/ensurepip/__init__.py"
    paths = [p for p in GNOME_OS_PATHS if "ensurepip" not in p] + [lib64]
    root = _make_tree(tmp_path, paths)
    assert check_requirements(root)["python-ensurepip"] == [lib64]


def test_modules_builtin_without_uinput_does_not_satisfy(tmp_path: Path) -> None:
    paths = [p for p in GNOME_OS_PATHS if "uinput" not in p]
    root = _make_tree(tmp_path, paths)
    (root / "usr/lib/modules/7.3.0/modules.builtin").write_text("kernel/fs/ext4/ext4.ko\n")
    assert check_requirements(root)["uinput"] == []


def test_dangling_absolute_symlink_counts_and_is_not_followed(tmp_path: Path) -> None:
    root = _make_tree(tmp_path, GNOME_OS_PATHS)
    # Inside a mounted deployment, absolute links point at the guest's /, which
    # on the host is a different tree. lexists() must accept them unresolved.
    os.symlink("/usr/libexec/does-not-exist-on-host", root / "usr/libexec/gnome-ponytail-daemon")
    assert check_requirements(root)["gnome-ponytail-daemon"] == ["usr/libexec/gnome-ponytail-daemon"]


@pytest.mark.parametrize(
    ("link", "pattern_hit"),
    [
        ("usr/lib64", "usr/lib64/python3.14/site-packages/gi/__init__.py"),
        ("usr/libexec", "usr/libexec/gnome-ponytail-daemon"),
    ],
)
def test_parent_symlink_escaping_guest_is_not_followed(
    tmp_path: Path, link: str, pattern_hit: str
) -> None:
    root = _make_tree(tmp_path / "guest", [p for p in GNOME_OS_PATHS if not p.startswith(link + "/")])
    host = tmp_path / "host"
    target = host / Path(pattern_hit).relative_to(link)
    target.parent.mkdir(parents=True)
    target.write_text("")
    if (root / link).exists():
        os.rename(root / link, tmp_path / "moved")
    os.symlink(host, root / link)
    hits = [h for hits in check_requirements(root).values() for h in hits]
    assert pattern_hit not in hits


def test_missing_os_release_fails_closed(tmp_path: Path) -> None:
    root = _make_tree(tmp_path, GNOME_OS_PATHS + ["usr/libexec/gnome-ponytail-daemon"], os_release=None)
    report = build_report(root)
    assert report["ok"] is False
    assert main([str(root)]) == 1


def test_parse_os_release_unquotes_and_skips_comments() -> None:
    parsed = parse_os_release('# comment\nID=org.gnome.os\nNAME="GNOME OS"\nX=\'y\'\n\nbogus\n')
    assert parsed == {"ID": "org.gnome.os", "NAME": "GNOME OS", "X": "y"}


def test_main_writes_report_and_fails_closed_on_stock_gnome_os(
    stock_gnome_os: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "results" / "guest-provenance.json"
    rc = main([str(stock_gnome_os), "--image-ref", "img", "--image-digest", "sha256:d", "--output", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["missing"] == ["gnome-ponytail-daemon"]
    assert data["image_digest"] == "sha256:d"
    assert "MISSING gnome-ponytail-daemon" in capsys.readouterr().out


def test_main_passes_complete_guest(gnome_os_with_ponytail: Path) -> None:
    assert main([str(gnome_os_with_ponytail)]) == 0


def test_main_rejects_non_directory_root(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope")]) == 2


ACTION = Path(__file__).parents[2] / ".github" / "actions" / "gnome-e2e" / "action.yml"


def test_action_runs_preflight_before_boot_for_extensions_only() -> None:
    text = ACTION.read_text(encoding="utf-8")
    install = text.partition("- name: Install OCI image and configure disk")[2].partition("\n    - name:")[0]
    assert install, "Install OCI image step not found in the gnome-e2e action"
    assert "GNOME_E2E_SUITE: ${{ inputs.suite }}" in install
    assert 'if [[ "${GNOME_E2E_SUITE}" == "extensions" ]]; then' in install
    assert "_testsuite/scripts/guest_preflight.py" in install
    assert "results/guest-provenance.json" in install
    # the loop device and mounts are released before the step fails
    assert install.index('sudo losetup -d "${LOOP}"') < install.index("PREFLIGHT_RC} -ne 0")
    assert text.index("guest_preflight.py") < text.index("- name: Boot VM with QEMU + KVM")
