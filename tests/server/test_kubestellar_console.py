"""Tests for KubeStellar Console and Kiosk Proxy integration.

Covers:
- Kiosk proxy listening on hostPort 8080
- /healthz endpoint returning status ok
- Local login options enabled by default (DEV_MODE=true, ALLOW_DEV_MODE_IN_CLUSTER=true, DEV_USER_LOGIN=admin) alongside GitHub OAuth
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def _find_container(deployment_doc: dict[str, Any], name: str) -> dict[str, Any] | None:
    containers = (
        deployment_doc.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )
    for c in containers:
        if c.get("name") == name:
            return c
    return None


class TestKioskProxyConfiguration:
    """Invariants for the KubeStellar kiosk proxy deployment and nginx configuration."""

    def test_kiosk_proxy_hostport_8080(self, files_dir: Path) -> None:
        proxy_path = (
            files_dir
            / "k0s"
            / "manifests"
            / "kubestellar"
            / "41-kubestellar-kiosk-proxy.yaml"
        )
        assert proxy_path.is_file(), f"Missing {proxy_path}"
        doc = yaml.safe_load(proxy_path.read_text(encoding="utf-8"))

        assert doc.get("kind") == "Deployment"
        assert doc.get("metadata", {}).get("name") == "kubestellar-kiosk-proxy"
        assert doc.get("metadata", {}).get("namespace") == "kubestellar-console"

        container = _find_container(doc, "kiosk-proxy")
        assert container is not None, "Container 'kiosk-proxy' not found in deployment"

        ports = container.get("ports", [])
        http_port = next((p for p in ports if p.get("name") == "http"), None)
        assert http_port is not None, "Missing 'http' port definition in kiosk-proxy"
        assert http_port.get("containerPort") == 8080
        assert http_port.get("hostPort") == 8080

    def test_kiosk_proxy_volume_mounts_and_image(self, files_dir: Path) -> None:
        proxy_path = (
            files_dir
            / "k0s"
            / "manifests"
            / "kubestellar"
            / "41-kubestellar-kiosk-proxy.yaml"
        )
        doc = yaml.safe_load(proxy_path.read_text(encoding="utf-8"))
        container = _find_container(doc, "kiosk-proxy")
        assert container is not None

        # Pinned nginx sha256 image
        image = container.get("image", "")
        assert "nginx@" in image and "sha256:62223d644fa234c3a1cc785ee14242ec47a77364226f1c811d2f669f96dc2ac8" in image

        # HostPath volume mount from /var/lib/k0s/kiosk
        mounts = container.get("volumeMounts", [])
        kiosk_mount = next((m for m in mounts if m.get("name") == "kiosk-assets"), None)
        assert kiosk_mount is not None
        assert kiosk_mount.get("mountPath") == "/etc/kubestellar-kiosk"
        assert kiosk_mount.get("readOnly") is True

        volumes = doc["spec"]["template"]["spec"].get("volumes", [])
        kiosk_vol = next((v for v in volumes if v.get("name") == "kiosk-assets"), None)
        assert kiosk_vol is not None
        assert kiosk_vol.get("hostPath", {}).get("path") == "/var/lib/k0s/kiosk"

    def test_console_service_isolated_no_public_hostport(self, files_dir: Path) -> None:
        console_path = (
            files_dir
            / "k0s"
            / "manifests"
            / "kubestellar"
            / "40-kubestellar-console.yaml"
        )
        docs = list(yaml.safe_load_all(console_path.read_text(encoding="utf-8")))

        service = next((d for d in docs if d and d.get("kind") == "Service"), None)
        assert service is not None
        assert service.get("spec", {}).get("type") == "ClusterIP"

        deployment = next((d for d in docs if d and d.get("kind") == "Deployment"), None)
        assert deployment is not None
        container = _find_container(deployment, "console")
        assert container is not None

        # Console deployment itself must NOT bind hostPort 8080 (only proxy does)
        for p in container.get("ports", []):
            assert "hostPort" not in p, "Console container must not directly expose hostPort; traffic goes via kiosk proxy"

    def test_kiosk_proxy_nginx_configuration(self, files_dir: Path) -> None:
        nginx_conf = files_dir / "k0s" / "kiosk" / "nginx.conf"
        assert nginx_conf.is_file(), f"Missing {nginx_conf}"
        content = nginx_conf.read_text(encoding="utf-8")

        assert "listen 8080;" in content
        assert "proxy_pass http://kubestellar-console.kubestellar-console.svc.cluster.local:8080;" in content
        assert 'proxy_set_header Accept-Encoding "";' in content
        assert "sub_filter '</head>' '<link rel=\"stylesheet\" href=\"/kiosk-gate.css\"></head>';" in content
        assert "sub_filter '</body>' '<script defer src=\"/kiosk-gate.js\"></script></body>';" in content


class TestHealthzAndEndpointContracts:
    """Invariants for the /healthz readiness endpoint and dashboard polling."""

    def test_kiosk_proxy_forwards_healthz(self, files_dir: Path) -> None:
        nginx_conf = files_dir / "k0s" / "kiosk" / "nginx.conf"
        content = nginx_conf.read_text(encoding="utf-8")
        # Nginx routes location / so /healthz is cleanly forwarded upstream to console
        assert "location / {" in content
        assert "proxy_pass http://kubestellar-console.kubestellar-console.svc.cluster.local:8080;" in content

    def test_healthz_polling_in_smoke_test_justfile(self, server_root: Path) -> None:
        justfile = server_root / "Justfile"
        assert justfile.is_file(), f"Missing {justfile}"
        content = justfile.read_text(encoding="utf-8")

        # Smoke test queries /healthz and expects {"status": "ok"}
        assert "curl" in content
        assert "/healthz" in content
        assert '.status == "ok"' in content
        # Also verifies root path returns HTTP 200
        assert 'ROOT_CODE=$(curl --silent --fail --max-time 2 --output /dev/null --write-out "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null || true)' in content
        assert '[ "$ROOT_CODE" = "200" ]' in content


class TestConsoleLoginOptions:
    """Invariants for default local login and GitHub OAuth configuration."""

    def test_local_login_dev_mode_enabled_by_default(self, files_dir: Path) -> None:
        console_path = (
            files_dir
            / "k0s"
            / "manifests"
            / "kubestellar"
            / "40-kubestellar-console.yaml"
        )
        docs = list(yaml.safe_load_all(console_path.read_text(encoding="utf-8")))
        deployment = next((d for d in docs if d and d.get("kind") == "Deployment"), None)
        assert deployment is not None
        container = _find_container(deployment, "console")
        assert container is not None

        env_vars = {item["name"]: item.get("value") for item in container.get("env", []) if "name" in item}

        assert env_vars.get("DEV_MODE") == "true", "DEV_MODE must be enabled by default"
        assert env_vars.get("ALLOW_DEV_MODE_IN_CLUSTER") == "true", (
            "ALLOW_DEV_MODE_IN_CLUSTER must be enabled by default"
        )
        assert env_vars.get("DEV_USER_LOGIN") == "admin", "DEV_USER_LOGIN must default to admin"

    def test_github_oauth_secret_references_in_console(self, files_dir: Path) -> None:
        console_path = (
            files_dir
            / "k0s"
            / "manifests"
            / "kubestellar"
            / "40-kubestellar-console.yaml"
        )
        docs = list(yaml.safe_load_all(console_path.read_text(encoding="utf-8")))
        deployment = next((d for d in docs if d and d.get("kind") == "Deployment"), None)
        assert deployment is not None
        container = _find_container(deployment, "console")
        assert container is not None

        secret_refs = {
            item["name"]: item.get("valueFrom", {}).get("secretKeyRef", {})
            for item in container.get("env", [])
            if "valueFrom" in item
        }

        for var_name, key_name, is_optional in [
            ("GITHUB_CLIENT_ID", "client-id", True),
            ("GITHUB_CLIENT_SECRET", "client-secret", True),
            ("JWT_SECRET", "jwt-secret", False),
        ]:
            ref = secret_refs.get(var_name)
            assert ref is not None, f"Missing secretKeyRef for {var_name}"
            assert ref.get("name") == "kubestellar-console-github-oauth"
            assert ref.get("key") == key_name
            assert ref.get("optional") is is_optional

    def test_github_oauth_secret_manifest_definition(self, files_dir: Path) -> None:
        secret_path = (
            files_dir
            / "k0s"
            / "manifests"
            / "kubestellar"
            / "01-kubestellar-console-github-oauth.yaml"
        )
        assert secret_path.is_file(), f"Missing {secret_path}"
        docs = list(yaml.safe_load_all(secret_path.read_text(encoding="utf-8")))

        secret = next((d for d in docs if d and d.get("kind") == "Secret"), None)
        assert secret is not None, "Secret document not found in 01-kubestellar-console-github-oauth.yaml"
        assert secret.get("metadata", {}).get("name") == "kubestellar-console-github-oauth"
        assert secret.get("metadata", {}).get("namespace") == "kubestellar-console"

        data_keys = set(secret.get("stringData", {}).keys()) | set(secret.get("data", {}).keys())
        assert {"client-id", "client-secret", "jwt-secret"}.issubset(data_keys)


class TestKioskGateAssets:
    """Invariants for client-side gate assets and styling."""

    def test_kiosk_gate_files_exist_and_functional(self, files_dir: Path) -> None:
        js_file = files_dir / "k0s" / "kiosk" / "kiosk-gate.js"
        css_file = files_dir / "k0s" / "kiosk" / "kiosk-gate.css"

        assert js_file.is_file(), f"Missing {js_file}"
        assert css_file.is_file(), f"Missing {css_file}"

        js_content = js_file.read_text(encoding="utf-8")
        assert "http://127.0.0.1:8585/health" in js_content
        assert "kc-has-session" in js_content
        assert re.search(r"kc-agent", js_content)

        css_content = css_file.read_text(encoding="utf-8")
        assert "z-index: 2147483647" in css_content
        assert "pointer-events: auto" in css_content
