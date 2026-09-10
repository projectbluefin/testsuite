"""Tests for systemd-sysext extension mechanics and k0s Kubernetes integration.

Covers:
- k0s sysext activation via k0s-first-boot.service
- Extension overlay merge into /usr
- Declarative manifest seeding via tmpfiles.d/k0s-manifests.conf
- k0scontroller.service activation and configuration
"""

from __future__ import annotations

from pathlib import Path
import yaml

from .conftest import load_systemd_conf, load_yaml


class TestK0sFirstBootActivation:
    """Activation flow of the k0s sysext on first boot."""

    def test_k0s_first_boot_unit_structure(self, files_dir: Path) -> None:
        service_path = files_dir / "os" / "systemd" / "system" / "k0s-first-boot.service"
        assert service_path.is_file(), f"Missing {service_path}"
        content = service_path.read_text(encoding="utf-8")

        assert "Wants=network-online.target" in content
        assert "After=network-online.target" in content
        assert "Wants=k0s-first-boot-fetch.service" in content
        assert "After=k0s-first-boot-fetch.service" in content
        # Offline boots must NOT fail activation if network fetch service fails
        assert "Requires=k0s-first-boot-fetch.service" not in content

        parser = load_systemd_conf(service_path)
        service = parser["Service"]
        assert service.get("Type") == "oneshot"
        assert service.get("Restart") == "on-failure"
        assert service.get("StateDirectory") == "k0s"

    def test_k0s_first_boot_activation_order(self, files_dir: Path) -> None:
        service_path = files_dir / "os" / "systemd" / "system" / "k0s-first-boot.service"
        content = service_path.read_text(encoding="utf-8")

        # Step 1: Pre-check that k0s.raw is available
        check_step = "ExecStartPre=/usr/bin/test -e /var/lib/k0s/k0s.raw"
        assert check_step in content

        # Step 2: Install raw image into /run/extensions
        stage_step = "ExecStart=/usr/bin/install -D -m 0644 /var/lib/k0s/k0s.raw /run/extensions/k0s.raw"
        assert stage_step in content

        # Step 3: Merge extension overlay into /usr
        merge_step = "ExecStart=/usr/bin/systemd-sysext merge"
        assert merge_step in content

        # Step 4: Seed manifests via tmpfiles
        tmpfiles_step = "ExecStart=/usr/bin/systemd-tmpfiles --create /usr/lib/tmpfiles.d/k0s-manifests.conf"
        assert tmpfiles_step in content

        # Step 5: Reload daemon to discover units from sysext overlay
        reload_step = "ExecStart=/usr/bin/systemctl daemon-reload"
        assert reload_step in content

        # Step 6: Enable and start k0scontroller service
        start_step = "ExecStart=/usr/bin/systemctl enable --now k0scontroller.service"
        assert start_step in content

        # Verify strict sequential ordering
        indices = [
            content.index(check_step),
            content.index(stage_step),
            content.index(merge_step),
            content.index(tmpfiles_step),
            content.index(reload_step),
            content.index(start_step),
        ]
        assert indices == sorted(indices), "k0s-first-boot execution steps out of required order"

    def test_k0s_first_boot_fetch_service_contract(self, files_dir: Path) -> None:
        fetch_path = files_dir / "os" / "systemd" / "system" / "k0s-first-boot-fetch.service"
        assert fetch_path.is_file(), f"Missing {fetch_path}"
        parser = load_systemd_conf(fetch_path)

        unit = parser["Unit"]
        # Skip fetch if k0s.raw is already present (e.g. seeded during installation)
        assert unit.get("ConditionPathExists") == "!/var/lib/k0s/k0s.raw"
        assert unit.get("Before") == "k0s-first-boot.service"

        service = parser["Service"]
        assert service.get("Type") == "oneshot"
        assert service.get("Restart") == "on-failure"
        assert service.get("ExecStart") == "/usr/bin/systemd-sysupdate --component=k0s update"

    def test_k0s_first_boot_preset_enabled(self, files_dir: Path) -> None:
        preset_file = (
            files_dir / "os" / "systemd" / "system-preset" / "zz-enable-k0s-first-boot.preset"
        )
        assert preset_file.is_file(), f"Missing {preset_file}"
        assert preset_file.read_text(encoding="utf-8").strip() == "enable k0s-first-boot.service"


class TestExtensionOverlayMerge:
    """Invariants for systemd-sysext overlay merge into /usr."""

    def test_extension_release_metadata(self, files_dir: Path) -> None:
        release_file = files_dir / "k0s" / "sysext" / "extension-release.k0s"
        assert release_file.is_file(), f"Missing {release_file}"
        fields = dict(
            line.strip().split("=", 1)
            for line in release_file.read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.strip().startswith("#")
        )
        assert fields.get("ID") == "_any", (
            "sysext ID must be _any so extension can merge across OS upgrades"
        )
        assert fields.get("NAME") == "k0s", (
            "sysext NAME must match current symlink 'k0s'"
        )

    def test_sysext_element_stages_to_usr_overlay(self, elements_dir: Path) -> None:
        sysext_bst = elements_dir / "oci" / "k0s-sysext.bst"
        assert sysext_bst.is_file(), f"Missing {sysext_bst}"
        content = sysext_bst.read_text(encoding="utf-8")

        # Staging into /usr paths
        assert "sysext/usr/bin" in content
        assert "sysext/usr/lib/systemd/system" in content
        assert "sysext/usr/lib/extension-release.d" in content
        assert "sysext/usr/lib/tmpfiles.d" in content
        assert "sysext/usr/share/k0s/manifests" in content
        assert "sysext/usr/share/k0s/kiosk" in content

        # EROFS formatting and zstd compression
        assert 'mkfs.erofs -d0 "${OUT}/${FNAME}" sysext' in content
        assert 'zstd -T0 -19 -q "${OUT}/${FNAME}" -o "${OUT}/${FNAME}.zst"' in content
        assert 'sha256sum --binary "${FNAME}.zst" > SHA256SUMS' in content

    def test_os_justfile_k8s_recipe_uses_sysext_merge(self, files_dir: Path) -> None:
        justfile = files_dir / "os" / "justfile"
        assert justfile.is_file(), f"Missing {justfile}"
        content = justfile.read_text(encoding="utf-8")
        assert "systemd-sysext merge" in content
        assert "systemd-tmpfiles --create /usr/lib/tmpfiles.d/k0s-manifests.conf" in content


class TestDeclarativeManifestSeeding:
    """Invariants for declarative manifest seeding via systemd-tmpfiles."""

    def test_k0s_manifests_tmpfiles_rules(self, files_dir: Path) -> None:
        conf_file = files_dir / "k0s" / "sysext" / "k0s-manifests.conf"
        assert conf_file.is_file(), f"Missing {conf_file}"
        lines = [line.strip() for line in conf_file.read_text(encoding="utf-8").splitlines() if line.strip()]

        # Directory creation
        assert any(
            line.startswith("d /var/lib/k0s/manifests 0755 root root") for line in lines
        )
        # Copy ArgoCD manifests
        assert any(
            "C+ /var/lib/k0s/manifests/argocd - - - - /usr/share/k0s/manifests/argocd" in line for line in lines
        )
        # Copy KubeStellar manifests
        assert any(
            "C+ /var/lib/k0s/manifests/kubestellar - - - - /usr/share/k0s/manifests/kubestellar" in line for line in lines
        )
        # Copy Kiosk proxy assets
        assert any(
            "C+ /var/lib/k0s/kiosk - - - - /usr/share/k0s/kiosk" in line for line in lines
        )

    def test_argocd_manifest_validity(self, files_dir: Path) -> None:
        argo_file = files_dir / "k0s" / "manifests" / "argocd" / "install.yaml"
        assert argo_file.is_file(), f"Missing {argo_file}"
        docs = list(yaml.safe_load_all(argo_file.read_text(encoding="utf-8")))
        assert len(docs) > 0, "ArgoCD manifest must contain valid Kubernetes documents"
        namespaces = [doc.get("metadata", {}).get("name") for doc in docs if doc and doc.get("kind") == "Namespace"]
        assert "argocd" in namespaces

    def test_kubestellar_manifests_validity(self, files_dir: Path) -> None:
        ks_dir = files_dir / "k0s" / "manifests" / "kubestellar"
        expected_manifests = [
            "00-kubeflex-crds.yaml",
            "10-kubeflex-operator.yaml",
            "20-postgres.yaml",
            "30-kubestellar-core.yaml",
            "40-kubestellar-console.yaml",
            "41-kubestellar-kiosk-proxy.yaml",
        ]
        for name in expected_manifests:
            path = ks_dir / name
            assert path.is_file(), f"Missing KubeStellar manifest {path}"
            docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
            assert len(docs) > 0, f"Empty or unparseable manifest: {path}"


class TestK0sControllerActivation:
    """Invariants for the k0s controller service unit and parameters."""

    def test_k0scontroller_unit_configuration(self, files_dir: Path) -> None:
        service_file = files_dir / "k0s" / "sysext" / "k0scontroller.service"
        assert service_file.is_file(), f"Missing {service_file}"
        parser = load_systemd_conf(service_file)

        assert parser.has_section("Service")
        service = parser["Service"]
        exec_start = service.get("ExecStart", "")

        # Key CLI flags for lightweight single-node server operation
        assert "--disable-components=helm,autopilot" in exec_start
        assert "--enable-worker" in exec_start
        assert "--single" in exec_start

        assert service.get("Restart") == "always"
        assert service.get("LimitNOFILE") == "1048576"

    def test_k0scontroller_discovered_via_sysext(self, elements_dir: Path) -> None:
        sysext_bst = elements_dir / "oci" / "k0s-sysext.bst"
        data = load_yaml(sysext_bst)
        sources = data.get("sources", [])
        sysext_src = next(
            (
                s for s in sources
                if isinstance(s, dict) and s.get("path") == "files/k0s/sysext"
            ),
            None,
        )
        assert sysext_src is not None, "k0s-sysext must include files/k0s/sysext in sources"
