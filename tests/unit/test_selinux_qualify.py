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


# ── canary diagnostics (#1141) ───────────────────────────────────────────────

SSHD_CANARY_AVC = CANARY_AVC.replace("httpd_t", "sshd_t").replace("900)", "901)")

DIAG_BLOCKED = """attempt_httpd_t=rc=229 status=229
attempt_sshd_t=rc=203 status=203
canary_type=sshd_t
canary_rc=203
canary_status=203
canary_stderr=Running as unit: run-u7.service Finished with result: exit-code Main processes terminated with: code=exited/status=203/EXEC
collector_context=unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023
cmdline=BOOT_IMAGE=/vmlinuz root=UUID=x console=ttyS0
seinfo_httpd_t=unavailable (no seinfo)
audit_log=missing
auditd=inactive
journal_kernel_avc=0
journal_avc=0
dmesg_avc=0
canary_ssh_rc=0
collect_rc=0
"""

DIAG_NOT_RUN = """attempt_httpd_t=rc=229 status=229
attempt_sshd_t=rc=229 status=229
canary_type=sshd_t
canary_rc=229
canary_status=229
canary_stderr=Main processes terminated with: code=exited/status=229/SELINUX_CONTEXT
seinfo_httpd_t=unavailable (no seinfo)
canary_ssh_rc=0
collect_rc=0
"""


def test_parse_diagnostics_keeps_values_with_equals_signs():
    diag = sq.parse_diagnostics(DIAG_BLOCKED + "free text line\n")
    assert diag["canary_type"] == "sshd_t"
    assert diag["cmdline"] == "BOOT_IMAGE=/vmlinuz root=UUID=x console=ttyS0"
    assert diag["attempt_httpd_t"] == "rc=229 status=229"
    assert "free text line" not in diag


def test_canary_types_cover_every_attempted_domain():
    assert sq.canary_types(sq.parse_diagnostics(DIAG_BLOCKED)) == ("httpd_t", "sshd_t")
    assert sq.canary_types({}) == (sq.CANARY_TYPE,)


def test_canary_detected_in_fallback_domain():
    types = sq.canary_types(sq.parse_diagnostics(DIAG_BLOCKED))
    assert sq.canary_result("", SSHD_CANARY_AVC, [], types)["detected"] is True
    assert sq.canary_result("", SSHD_CANARY_AVC, [])["detected"] is False


def test_canary_failure_not_run_when_no_domain_was_blocked():
    result = sq.canary_result("", "", [])
    reason, message = sq.canary_failure(result, sq.parse_diagnostics(DIAG_NOT_RUN))
    assert reason == "not-run"
    assert "could not run" in message
    assert "229/SELINUX_CONTEXT" in message


def test_canary_failure_unknown_when_probe_executed_without_denial():
    diag = sq.parse_diagnostics(DIAG_NOT_RUN.replace("229", "0"))
    reason, message = sq.canary_failure(sq.canary_result("", "", []), diag)
    assert reason == "unknown"
    assert "executed" in message
    assert "no candidate" not in message


def test_canary_failure_unknown_when_early_read_failure_precedes_context_failure():
    diag = sq.parse_diagnostics(DIAG_NOT_RUN.replace(
        "attempt_httpd_t=rc=229 status=229", "attempt_httpd_t=rc=1 status=1"))
    reason, message = sq.canary_failure(sq.canary_result("", "", []), diag)
    assert reason == "unknown"
    assert "httpd_t (status 1)" in message
    assert "no candidate" not in message


def test_canary_failure_unknown_when_early_success_precedes_context_failure():
    diag = sq.parse_diagnostics(DIAG_NOT_RUN.replace(
        "attempt_httpd_t=rc=229 status=229", "attempt_httpd_t=rc=0 status=0"))
    reason, message = sq.canary_failure(sq.canary_result("", "", []), diag)
    assert reason == "unknown"
    assert "httpd_t" in message


def test_canary_failure_not_run_without_guest_output():
    reason, message = sq.canary_failure(
        sq.canary_result("", "", []), {"canary_ssh_rc": "255", "collect_rc": "0"}
    )
    assert reason == "not-run"
    assert "255" in message


def test_canary_failure_unknown_when_exec_failed_but_not_collected():
    reason, message = sq.canary_failure(
        sq.canary_result("", "", []), sq.parse_diagnostics(DIAG_BLOCKED)
    )
    assert reason == "unknown"
    assert "does not show whether SELinux caused it" in message
    assert "audit_log=missing" in message
    assert "journal_kernel_avc=0" in message


def test_canary_failure_unknown_when_read_failed_after_exec():
    diag = sq.parse_diagnostics(
        DIAG_BLOCKED.replace("rc=203 status=203", "rc=1 status=1")
        .replace("canary_rc=203", "canary_rc=1")
        .replace("canary_status=203", "canary_status=1")
    )
    reason, message = sq.canary_failure(sq.canary_result("", "", []), diag)
    assert reason == "unknown"
    assert "(status 1)" in message
    assert "reading the protected file failed" in message
    assert "no denial was produced" not in message


def test_canary_failure_reports_each_attempts_output():
    diag = sq.parse_diagnostics(
        DIAG_NOT_RUN + "canary_output_httpd_t=first httpd_t failure\n"
        "canary_output_sshd_t=second sshd_t failure\n"
    )
    assert sq.canary_types(diag) == ("httpd_t", "sshd_t")
    reason, message = sq.canary_failure(sq.canary_result("", "", []), diag)
    assert reason == "not-run"
    assert "httpd_t: first httpd_t failure" in message
    assert "sshd_t: second sshd_t failure" in message


def test_canary_failure_not_collected_when_collector_fails():
    diag = sq.parse_diagnostics(DIAG_BLOCKED.replace("collect_rc=0", "collect_rc=1"))
    reason, message = sq.canary_failure(sq.canary_result("", "", []), diag)
    assert reason == "not-collected"
    assert "collector failed (exit 1)" in message


def test_canary_failure_permissive_and_allowlisted():
    permissive = CANARY_AVC.replace("permissive=0", "permissive=1")
    assert sq.canary_failure(sq.canary_result("", permissive, []), {})[0] == "permissive"
    entry = {
        "source_context": "system_u:system_r:httpd_t:s0",
        "target_context": "system_u:object_r:bin_t:s0",
        "permission": "entrypoint",
        "comm": "(cat)",
        "reason": "would hide the canary",
    }
    assert sq.canary_failure(sq.canary_result("", CANARY_AVC, [entry]), {})[0] == "allowlisted"


def test_canary_failure_unknown_without_diagnostics():
    assert sq.canary_failure(sq.canary_result("", "", []), None)[0] == "unknown"


def test_canary_cli_names_reason_and_records_diagnostics(tmp_path):
    empty = tmp_path / "empty.log"
    empty.write_text("")
    diag = tmp_path / "diag.txt"
    diag.write_text(DIAG_BLOCKED)
    out = tmp_path / "canary.json"
    result = _run(
        "canary", str(empty), str(empty), "--allowlist", str(_allowlist(tmp_path, [])),
        "--diagnostics", str(diag), "--json", str(out),
    )
    assert result.returncode == 1
    assert "did not reach the AVC gate (unknown)" in result.stdout
    payload = json.loads(out.read_text())
    assert payload["reason"] == "unknown"
    assert payload["diagnostics"]["audit_log"] == "missing"
    assert payload["canary_types"] == ["httpd_t", "sshd_t"]


def test_canary_cli_detects_fallback_domain(tmp_path):
    before = tmp_path / "before.log"
    before.write_text("")
    after = tmp_path / "after.log"
    after.write_text(SSHD_CANARY_AVC + "\n")
    diag = tmp_path / "diag.txt"
    diag.write_text(DIAG_BLOCKED)
    out = tmp_path / "canary.json"
    result = _run(
        "canary", str(before), str(after), "--allowlist", str(_allowlist(tmp_path, [])),
        "--diagnostics", str(diag), "--json", str(out),
    )
    assert result.returncode == 0, result.stdout
    assert json.loads(out.read_text())["reason"] == "detected"


def test_canary_cli_missing_diagnostics_file_is_not_run(tmp_path):
    empty = tmp_path / "empty.log"
    empty.write_text("")
    result = _run(
        "canary", str(empty), str(empty), "--allowlist", str(_allowlist(tmp_path, [])),
        "--diagnostics", str(tmp_path / "absent.txt"),
    )
    assert result.returncode == 1
    assert "(not-run)" in result.stdout


# ── workflow wiring ──────────────────────────────────────────────────────────


def _e2e() -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / "e2e.yml").read_text())


def _steps() -> dict[str, dict]:
    return {step.get("name"): step for step in _e2e()["jobs"]["e2e"]["steps"]}


def test_guest_kernel_args_do_not_disable_selinux():
    install = _steps()["Install OCI image and configure disk"]["run"]
    kernel_args = next(line for line in install.splitlines() if 'KERNEL_ARGS="root=' in line)
    for arg in ("selinux=0", "enforcing=0", "security=none"):
        assert arg not in kernel_args
    # selinux=0 is only appended when a caller opts out of enforcing mode.
    assert install.count("selinux=0") == 1
    guard = install.index('if [[ "${SELINUX_ENFORCING}" != "true" ]]; then')
    assert guard < install.index('KERNEL_ARGS="${KERNEL_ARGS} selinux=0"') < install.index(
        'echo "KERNEL_ARGS=${KERNEL_ARGS}" >> "$GITHUB_ENV"'
    )


def test_enforcing_mode_defaults_on_and_can_be_opted_out():
    selinux_input = _e2e()[True]["workflow_call"]["inputs"]["selinux_enforcing"]
    assert selinux_input["type"] == "boolean"
    assert selinux_input["default"] is True
    install_step = _steps()["Install OCI image and configure disk"]
    assert "inputs.selinux_enforcing" in install_step["env"]["SELINUX_ENFORCING"]
    install = install_step["run"]
    opt_in = install.index('if [[ "${SELINUX_ENFORCING}" == "true" ]]; then')
    assert opt_in < install.index("selinux_qualify.py expected-mode") < install.index('SELINUX_INFO="off none"')
    assert _steps()["Verify SELinux enforcing"]["if"] == "env.SELINUX_EXPECTED != 'off'"
    assert "env.SELINUX_EXPECTED == 'enforcing'" in _steps()["SELinux denial gate"]["if"]


def test_manual_dispatch_defaults_to_enforcing():
    manual = yaml.safe_load((ROOT / ".github" / "workflows" / "manual.yml").read_text())
    assert manual[True]["workflow_dispatch"]["inputs"]["selinux_enforcing"]["default"] == "true"
    passed = manual["jobs"]["test"]["with"]["selinux_enforcing"]
    assert passed == "${{ github.event.inputs.selinux_enforcing == 'true' }}"


def test_sparse_checkout_ships_selinux_helpers():
    checkout = _steps()["Checkout testsuite"]["with"]["sparse-checkout"].split()
    for path in (
        "scripts/selinux_qualify.py",
        "scripts/selinux_canary.sh",
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
    # rindex: the install retry loop unmounts discarded attempts earlier; the
    # final unmount is the one that ends disk configuration before boot.
    umount = install.rindex("sudo umount /mnt/root")
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
    canary = gate.index("scripts/selinux_canary.sh")
    after = gate.index("avc-after-canary.log")
    check = gate.index("selinux_qualify.py canary")
    assert collect < verdict < canary < after < check
    assert '--diagnostics "${DIAG}"' in gate
    assert 'exit "${RC}"' in gate


def test_gate_records_why_the_canary_failed():
    gate = _steps()["SELinux denial gate"]["run"]
    assert 'canary_ssh_rc=${CANARY_SSH_RC}' in gate
    assert 'collect_rc=${COLLECT_RC}' in gate
    # The diagnostics land in results/selinux (uploaded) and the step summary.
    assert 'DIAG="${D}/canary-diagnostics.txt"' in gate
    summary = gate[gate.index("### SELinux qualification"):gate.index('"$GITHUB_STEP_SUMMARY"')]
    assert 'cat "${DIAG}"' in summary
    assert '"${CANARY_OUT}"' in summary


def test_canary_script_triggers_denial_and_logs_evidence():
    script = (ROOT / "scripts" / "selinux_canary.sh").read_text()
    assert "SELinuxContext=system_u:system_r:${type}:s0" in script
    assert "CANDIDATES=(httpd_t " in script
    assert "--quiet" not in script
    for evidence in (
        "/proc/cmdline",
        "seinfo -t httpd_t",
        "/var/log/audit/audit.log",
        "journalctl -k",
        "canary_rc=",
        "canary_stderr=",
        "canary_output_${type}=",
    ):
        assert evidence in script


def test_collector_reads_audit_log_and_ring_buffer():
    script = (ROOT / "scripts" / "selinux_collect_avc.sh").read_text()
    assert "ausearch -m AVC,USER_AVC --raw" in script
    assert "grep -hF 'avc:' /var/log/audit/audit.log*" in script
    assert "dmesg" in script
