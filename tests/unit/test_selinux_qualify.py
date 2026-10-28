"""Unit tests for scripts/selinux_qualify.py and its e2e workflow wiring.

The e2e VM boots enforcing (#1024). These tests lock in that the helpers
fail closed: a guest that is not enforcing, an unexpected denial, or a
collection path that cannot see a deliberate denial must all fail.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import selinux_qualify as sq  # noqa: E402

SCRIPT = ROOT / "scripts" / "selinux_qualify.py"

AUSEARCH_AVC = (
    'type=AVC msg=audit(1761555000.101:412): avc:  denied  { read } for  pid=812 '
    'comm="gnome-shell" name="foo" dev="vda3" ino=42 '
    "scontext=unconfined_u:unconfined_r:xdm_t:s0-s0:c0.c1023 "
    "tcontext=system_u:object_r:shadow_t:s0 tclass=file permissive=0"
)
KMSG_SAME_EVENT = (
    "audit: type=1400 audit(1761555000.101:412): avc:  denied  { read } for  pid=812 "
    'comm="gnome-shell" name="foo" dev="vda3" ino=42 '
    "scontext=unconfined_u:unconfined_r:xdm_t:s0-s0:c0.c1023 "
    "tcontext=system_u:object_r:shadow_t:s0 tclass=file permissive=0"
)
USER_AVC = (
    "type=USER_AVC msg=audit(1761555001.200:413): pid=700 uid=81 auid=4294967295 "
    "ses=4294967295 subj=system_u:system_r:system_dbusd_t:s0 msg='avc:  denied  "
    "{ send_msg } for msgtype=method_call interface=org.example.Foo member=Bar "
    "dest=org.example spid=900 tpid=901 scontext=system_u:system_r:init_t:s0 "
    "tcontext=system_u:system_r:colord_t:s0 tclass=dbus permissive=0 "
    "exe=\"/usr/bin/dbus-broker\" sauid=81 hostname=? addr=? terminal=?'"
)
PERMISSIVE_AVC = (
    "type=AVC msg=audit(1761555002.300:414): avc:  denied  { getattr } for  pid=9 "
    'comm="foo" scontext=system_u:system_r:foo_t:s0 '
    "tcontext=system_u:object_r:etc_t:s0 tclass=file permissive=1"
)
GRANTED = (
    "type=AVC msg=audit(1761555003.400:415): avc:  granted  { setsecparam } for  pid=1 "
    'comm="load_policy" scontext=system_u:system_r:kernel_t:s0 '
    "tcontext=system_u:object_r:security_t:s0 tclass=security"
)
CANARY_AVC = (
    "audit: type=1400 audit(1761555100.500:900): avc:  denied  { entrypoint } for  "
    'pid=1234 comm="(cat)" path="/usr/bin/cat" dev="vda3" ino=77 '
    "scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:bin_t:s0 "
    "tclass=file permissive=0"
)

ALLOW_XDM_SHADOW = {
    "source_context": "system_u:system_r:xdm_t:s0",
    "target_context": "system_u:object_r:shadow_t:s0",
    "permission": "read",
    "comm": "gnome-shell",
    "reason": "test fixture",
}


def _allowlist(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "allow.yaml"
    path.write_text(yaml.safe_dump({"allowed_denials": entries}), encoding="utf-8")
    return path


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


# ── expected mode ────────────────────────────────────────────────────────────


def _deploy(tmp_path: Path, config: str | None, policy: str | None = "targeted") -> Path:
    deploy = tmp_path / "deploy"
    selinux = deploy / "etc" / "selinux"
    selinux.mkdir(parents=True)
    if config is not None:
        (selinux / "config").write_text(config, encoding="utf-8")
    if policy:
        contexts = selinux / policy / "contexts" / "files"
        contexts.mkdir(parents=True)
        (contexts / "file_contexts").write_text("/.* system_u:object_r:default_t:s0\n")
    return deploy


def test_policy_store_requires_enforcing(tmp_path):
    deploy = _deploy(tmp_path, "SELINUX=enforcing\nSELINUXTYPE=targeted\n")
    assert sq.expected_mode(deploy) == ("enforcing", "targeted")


def test_permissive_config_with_policy_still_requires_enforcing(tmp_path):
    deploy = _deploy(tmp_path, "# comment\nSELINUX=permissive\nSELINUXTYPE=targeted\n")
    assert sq.expected_mode(deploy) == ("enforcing", "targeted")


def test_policy_type_comes_from_config(tmp_path):
    deploy = _deploy(tmp_path, 'SELINUX=enforcing\nSELINUXTYPE="mls"\n', policy="mls")
    assert sq.expected_mode(deploy) == ("enforcing", "mls")


def test_image_without_policy_store_is_unsupported(tmp_path):
    deploy = _deploy(tmp_path, None, policy=None)
    assert sq.expected_mode(deploy) == ("unsupported", "-")
    assert _run("expected-mode", str(deploy)).stdout.strip() == "unsupported -"


# ── check-mode ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("observed", ["Permissive", "Disabled", "", "bash: getenforce: not found"])
def test_check_mode_rejects_anything_but_enforcing(observed):
    result = _run("check-mode", "enforcing", observed)
    assert result.returncode == 1
    assert "::error::" in result.stdout


def test_check_mode_accepts_enforcing():
    assert _run("check-mode", "enforcing", "Enforcing\n").returncode == 0


def test_check_mode_unsupported_is_reported_not_silent():
    result = _run("check-mode", "unsupported", "")
    assert result.returncode == 0
    assert "unsupported" in result.stdout


def test_check_mode_unsupported_but_enforcing_is_inconsistent():
    assert _run("check-mode", "unsupported", "Enforcing").returncode == 1


# ── unlabeled ────────────────────────────────────────────────────────────────


def _labelled_tree(tmp_path: Path, monkeypatch, labelled: set[str]) -> Path:
    root = tmp_path / "dep"
    (root / "etc" / "ssh" / "sshd_config.d").mkdir(parents=True)
    (root / "etc" / "passwd").write_text("root:x:0:0::/root:/bin/sh\n")
    (root / "etc" / "ssh" / "sshd_config.d" / "00-ci-auth.conf").write_text("x\n")
    (root / "etc" / "masked.service").symlink_to("/dev/null")
    monkeypatch.setattr(
        sq, "has_label", lambda path: str(Path(path).relative_to(root)) in labelled
    )
    return root


def test_unlabeled_lists_new_files_and_symlinks_without_following(tmp_path, monkeypatch):
    root = _labelled_tree(tmp_path, monkeypatch, {"etc", "etc/passwd", "etc/ssh"})
    found = sq.unlabeled(str(root), [str(root / "etc")], set())
    assert [str(Path(p).relative_to(root)) for p in found] == [
        "etc/masked.service",
        "etc/ssh/sshd_config.d",
        "etc/ssh/sshd_config.d/00-ci-auth.conf",
    ]


def test_unlabeled_excludes_candidate_baseline(tmp_path, monkeypatch):
    root = _labelled_tree(tmp_path, monkeypatch, {"etc", "etc/ssh"})
    baseline = {str(root / "etc" / "passwd")}
    found = sq.unlabeled(str(root), [str(root / "etc")], baseline)
    assert str(root / "etc" / "passwd") not in found
    assert str(root / "etc" / "masked.service") in found


def test_unlabeled_rejects_paths_outside_root(tmp_path):
    with pytest.raises(ValueError):
        sq.unlabeled(str(tmp_path / "a"), [str(tmp_path / "b")], set())
    result = _run("unlabeled", "--root", str(tmp_path / "a"), str(tmp_path / "b"))
    assert result.returncode == 2


def test_unlabeled_missing_path_is_empty(tmp_path):
    assert sq.unlabeled(str(tmp_path), [str(tmp_path / "absent")], set()) == []


def test_has_label_false_for_missing_path(tmp_path):
    assert sq.has_label(str(tmp_path / "missing")) is False


# ── parsing ──────────────────────────────────────────────────────────────────


def test_parse_ausearch_kmsg_and_user_avc():
    denials = sq.parse_denials("\n".join([AUSEARCH_AVC, USER_AVC, GRANTED, "noise"]))
    assert len(denials) == 2
    kernel, user = denials
    assert kernel["permissions"] == ["read"]
    assert kernel["comm"] == "gnome-shell"
    assert sq.selinux_type(kernel["scontext"]) == "xdm_t"
    assert kernel["tclass"] == "file"
    assert kernel["permissive"] is False
    assert user["tclass"] == "dbus"
    assert sq.selinux_type(user["tcontext"]) == "colord_t"


def test_same_event_from_two_sinks_counts_once():
    assert len(sq.parse_denials(f"{AUSEARCH_AVC}\n{KMSG_SAME_EVENT}\n")) == 1


def test_records_without_audit_id_stay_distinct():
    a = "AVC avc:  denied  { read } for pid=1 comm=\"a\" scontext=s:r:a_t:s0 tcontext=s:r:b_t:s0 tclass=file permissive=0"
    b = a.replace("pid=1", "pid=2")
    assert len(sq.parse_denials(f"{a}\n{b}\n")) == 2


# ── gate ─────────────────────────────────────────────────────────────────────


def test_gate_fails_on_unexpected_denial(tmp_path):
    log = tmp_path / "avc.log"
    log.write_text(AUSEARCH_AVC + "\n")
    out = tmp_path / "verdict.json"
    result = _run("gate", str(log), "--allowlist", str(_allowlist(tmp_path, [])), "--json", str(out))
    assert result.returncode == 1
    assert "unexpected SELinux denial" in result.stdout
    assert json.loads(out.read_text())["passed"] is False


def test_gate_passes_clean_log(tmp_path):
    log = tmp_path / "avc.log"
    log.write_text(GRANTED + "\n")
    allow = _allowlist(tmp_path, [])
    assert _run("gate", str(log), "--allowlist", str(allow)).returncode == 0


def test_gate_accepts_narrow_allowlist_match(tmp_path):
    log = tmp_path / "avc.log"
    log.write_text(AUSEARCH_AVC + "\n")
    allow = _allowlist(tmp_path, [ALLOW_XDM_SHADOW])
    result = _run("gate", str(log), "--allowlist", str(allow))
    assert result.returncode == 0
    assert "allowlisted" in result.stdout


@pytest.mark.parametrize(
    "override",
    [
        {"comm": "gdm"},
        {"permission": "read write"},
        {"target_context": "system_u:object_r:etc_t:s0"},
        {"source_context": "system_u:system_r:init_t:s0"},
        {"tclass": "dir"},
    ],
)
def test_allowlist_does_not_widen(override):
    entries = [{**ALLOW_XDM_SHADOW, **override}]
    verdict = sq.evaluate(AUSEARCH_AVC, entries)
    assert verdict["passed"] is False


def test_allowlist_entry_needs_reason(tmp_path):
    entry = {**ALLOW_XDM_SHADOW, "reason": ""}
    with pytest.raises(ValueError, match="reason"):
        sq.load_allowlist(_allowlist(tmp_path, [entry]))
    log = tmp_path / "avc.log"
    log.write_text("")
    assert _run("gate", str(log), "--allowlist", str(_allowlist(tmp_path, [entry]))).returncode == 2


def test_permissive_domain_denial_is_reported_not_fatal():
    verdict = sq.evaluate(PERMISSIVE_AVC, [])
    assert verdict["passed"] is True
    assert len(verdict["permissive_domain"]) == 1


def test_repository_allowlist_is_valid():
    sq.load_allowlist(ROOT / "selinux_allowlist.yaml")


# ── canary ───────────────────────────────────────────────────────────────────


def test_canary_detected_when_new_denial_fails_gate(tmp_path):
    before = tmp_path / "before.log"
    after = tmp_path / "after.log"
    before.write_text(GRANTED + "\n")
    after.write_text(f"{GRANTED}\n{CANARY_AVC}\n")
    out = tmp_path / "canary.json"
    result = _run(
        "canary", str(before), str(after), "--allowlist", str(_allowlist(tmp_path, [])),
        "--json", str(out),
    )
    assert result.returncode == 0, result.stdout
    payload = json.loads(out.read_text())
    assert payload["detected"] is True
    assert payload["gate_failed"] is True


def test_canary_missing_fails_closed(tmp_path):
    before = tmp_path / "before.log"
    before.write_text(AUSEARCH_AVC + "\n")
    allow = _allowlist(tmp_path, [])
    result = _run("canary", str(before), str(before), "--allowlist", str(allow))
    assert result.returncode == 1
    assert "did not reach the AVC gate" in result.stdout


def test_canary_already_present_before_does_not_count():
    assert sq.canary_result(CANARY_AVC, CANARY_AVC, [])["detected"] is False


def test_allowlisting_the_canary_breaks_detection():
    entry = {
        "source_context": "system_u:system_r:httpd_t:s0",
        "target_context": "system_u:object_r:bin_t:s0",
        "permission": "entrypoint",
        "comm": "(cat)",
        "reason": "would hide the canary",
    }
    assert sq.canary_result("", CANARY_AVC, [entry])["detected"] is False


# ── workflow wiring ──────────────────────────────────────────────────────────


def _e2e() -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / "e2e.yml").read_text())


def _steps() -> dict[str, dict]:
    return {step.get("name"): step for step in _e2e()["jobs"]["e2e"]["steps"]}


def test_guest_kernel_args_do_not_disable_selinux():
    text = (ROOT / ".github" / "workflows" / "e2e.yml").read_text()
    install = _steps()["Install OCI image and configure disk"]["run"]
    kernel_args = next(line for line in install.splitlines() if "KERNEL_ARGS=\"" in line)
    for arg in ("selinux=0", "enforcing=0", "security=none"):
        assert arg not in kernel_args
    assert "selinux=0" not in text


def test_sparse_checkout_ships_selinux_helpers():
    checkout = _steps()["Checkout testsuite"]["with"]["sparse-checkout"].split()
    for path in (
        "scripts/selinux_qualify.py",
        "scripts/selinux_collect_avc.sh",
        "selinux_allowlist.yaml",
    ):
        assert path in checkout
        assert (ROOT / path).exists()


def test_harness_files_are_labeled_before_unmount_with_candidate_setfiles():
    install = _steps()["Install OCI image and configure disk"]["run"]
    baseline = install.index("baseline-unlabeled-var.txt")
    first_injection = install.index('"${DEP}/etc/ssh/sshd_config.d/"')
    labeling = install.index("setfiles -m -F -r")
    umount = install.index("sudo umount /mnt/root")
    last_injection = install.index('sudo cp /tmp/vm_key.pub "${DEP}/etc/ssh/ci-authorized-keys"')
    assert baseline < first_injection < last_injection < labeling < umount
    assert '"${IMAGE}" setfiles' in install
    assert "--exclude" in install
    assert "still unlabeled after setfiles" in install


def test_enforcing_verified_after_boot_and_after_suite():
    steps = list(_steps())
    verify = steps.index("Verify SELinux enforcing")
    assert steps.index("Wait for SSH") < verify < steps.index("Run behave suite")
    gate_index = steps.index("SELinux denial gate")
    assert steps.index("Run behave suite") < gate_index
    assert 'check-mode "${SELINUX_EXPECTED:-enforcing}"' in _steps()["Verify SELinux enforcing"]["run"]
    gate = _steps()["SELinux denial gate"]
    assert "always()" in gate["if"]
    assert "check-mode enforcing" in gate["run"]
    assert "ControlMaster=no" in gate["run"]


def test_gate_runs_canary_after_scenario_collection():
    gate = _steps()["SELinux denial gate"]["run"]
    collect = gate.index("avc-scenario.log")
    verdict = gate.index("selinux_qualify.py gate")
    canary = gate.index("SELinuxContext=system_u:system_r:httpd_t:s0")
    check = gate.index("selinux_qualify.py canary")
    assert collect < verdict < canary < check
    assert "StandardOutput=null" in gate
    assert 'exit "${RC}"' in gate
