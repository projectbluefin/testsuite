"""Option A for #908: the extension test session holds no guest admin access.

The maintainer ruling on #908 keeps the desktop account the tests and candidate
extensions run as apart from harness administration: no guest login details,
no SSH key, no password-free sudo, no host management sockets and no host
mounts. ``scripts/guest_accounts.py`` provisions that layout before boot,
``scripts/guest_session_isolation.py`` proves it on the booted guest, and the
``gnome-e2e`` action runs behave as the desktop account without
qecore-headless (which needs sudo). These tests pin each piece.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import guest_accounts, guest_session_isolation as iso

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / ".github/actions/gnome-e2e/action.yml"
CANARY = ROOT / ".github/workflows/gnomeos-canary.yml"


# ── guest_accounts.py ─────────────────────────────────────────────────────


def _guest(tmp_path, passwd="root:x:0:0:root:/root:/bin/bash\n"):
    deploy, var = tmp_path / "deploy", tmp_path / "var"
    (deploy / "etc").mkdir(parents=True)
    (deploy / "etc/passwd").write_text(passwd)
    var.mkdir()
    owners = {}
    return deploy, var, owners, lambda path, uid, gid: owners.__setitem__(Path(path), (uid, gid))


def test_desktop_account_gets_no_key_and_no_sudo(tmp_path):
    deploy, var, owners, chown = _guest(tmp_path)
    guest_accounts.provision(deploy, var, "ssh-ed25519 AAAA harness", chown)

    desktop_home = var / "home/bluefin-test"
    assert desktop_home.is_dir()
    assert not (desktop_home / ".ssh/authorized_keys").exists()
    assert not (deploy / "etc/sudoers.d/zz-bluefin-test").exists()
    assert "bluefin-test:!:" in (deploy / "etc/shadow").read_text()
    assert owners[desktop_home] == (1001, 1001)


def test_harness_account_holds_key_and_sudo_behind_a_closed_home(tmp_path):
    deploy, var, owners, chown = _guest(tmp_path)
    guest_accounts.provision(deploy, var, "ssh-ed25519 AAAA harness", chown)

    home = var / "home/gnome-e2e-harness"
    keys = home / ".ssh/authorized_keys"
    assert keys.read_text() == "ssh-ed25519 AAAA harness\n"
    assert keys.stat().st_mode & 0o777 == 0o600
    assert home.stat().st_mode & 0o777 == 0o700
    assert owners[keys] == (1002, 1002)
    grant = deploy / "etc/sudoers.d/zz-gnome-e2e-harness"
    assert grant.read_text() == "gnome-e2e-harness ALL=(ALL) NOPASSWD:ALL\n"
    assert grant.stat().st_mode & 0o777 == 0o440
    passwd = (deploy / "etc/passwd").read_text()
    assert "gnome-e2e-harness:x:1002:1002:" in passwd
    assert "bluefin-test:x:1001:1001:" in passwd


def test_existing_desktop_key_and_sudo_grant_are_removed(tmp_path):
    deploy, var, _, chown = _guest(tmp_path)
    ssh = var / "home/bluefin-test/.ssh"
    ssh.mkdir(parents=True)
    (ssh / "authorized_keys").write_text("old key\n")
    (deploy / "etc/sudoers.d").mkdir()
    (deploy / "etc/sudoers.d/zz-bluefin-test").write_text("bluefin-test ALL=(ALL) NOPASSWD:ALL\n")

    guest_accounts.provision(deploy, var, "ssh-ed25519 AAAA harness", chown)

    assert not (ssh / "authorized_keys").exists()
    assert not (deploy / "etc/sudoers.d/zz-bluefin-test").exists()


def test_provisioning_twice_does_not_duplicate_accounts(tmp_path):
    deploy, var, _, chown = _guest(tmp_path)
    guest_accounts.provision(deploy, var, "key", chown)
    guest_accounts.provision(deploy, var, "key", chown)
    names = [line.split(":")[0] for line in (deploy / "etc/passwd").read_text().splitlines()]
    assert names.count("bluefin-test") == 1
    assert names.count("gnome-e2e-harness") == 1


def test_uid_clash_fails_closed(tmp_path):
    deploy, var, _, chown = _guest(tmp_path, "someone:x:1002:1002::/home/someone:/bin/sh\n")
    with pytest.raises(guest_accounts.ProvisionError, match="uid 1002"):
        guest_accounts.provision(deploy, var, "key", chown)


def test_empty_key_fails_closed(tmp_path):
    deploy, var, _, chown = _guest(tmp_path)
    with pytest.raises(guest_accounts.ProvisionError, match="empty"):
        guest_accounts.provision(deploy, var, "  \n", chown)


def test_symlinked_sudoers_grant_is_not_written_through(tmp_path):
    deploy, var, _, chown = _guest(tmp_path)
    (deploy / "etc/sudoers.d").mkdir()
    outside = tmp_path / "outside"
    (deploy / "etc/sudoers.d/zz-gnome-e2e-harness").symlink_to(outside)
    with pytest.raises(guest_accounts.ProvisionError, match="symlink"):
        guest_accounts.provision(deploy, var, "key", chown)
    assert not outside.exists()


# ── guest_session_isolation.py ────────────────────────────────────────────

PASSWD = {
    "bluefin-test": "bluefin-test:x:1001:1001:Bluefin Test:/var/home/bluefin-test:/bin/bash",
    "gnome-e2e-harness": "gnome-e2e-harness:x:1002:1002::/var/home/gnome-e2e-harness:/bin/bash",
}


SSHD_DEFAULT = (
    "authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2\n"
    "authorizedkeyscommand none\n"
)


def _runner(sudo="User bluefin-test is not allowed to run sudo on gnomeos.",
            groups="bluefin-test", shadow="bluefin-test:!:19000:0:99999:7:::",
            sshd=(0, SSHD_DEFAULT)):
    def run(cmd):
        if cmd[0] == "sshd":
            assert cmd[1:3] == ["-T", "-C"] and "user=bluefin-test" in cmd[3]
            return sshd
        if cmd[:2] == ["getent", "passwd"]:
            entry = PASSWD.get(cmd[2])
            return (0, entry + "\n") if entry else (2, "")
        if cmd[:2] == ["getent", "shadow"]:
            return 0, shadow + "\n"
        if cmd[0] == "sudo":
            return 0, sudo + "\n"
        if cmd[:2] == ["id", "-nG"]:
            return 0, groups + "\n"
        raise AssertionError(f"unexpected command {cmd}")
    return run


STOCK_POLKIT = {
    "/usr/share/polkit-1/rules.d/50-default.rules":
        'polkit.addAdminRule(function(action, subject) { return ["unix-group:wheel"]; });',
    "/usr/share/polkit-1/rules.d/49-wheel.rules":
        'polkit.addRule(function(a, s) { if (s.isInGroup("wheel")) return polkit.Result.YES; });',
}


def _report(run=None, keys=(), home_mode=0o700, mounts="/dev/vda3 / ext4 rw 0 0\n", sockets=(),
            polkit=None):
    present = set(keys) | set(sockets)
    return iso.build_report(
        "bluefin-test", "gnome-e2e-harness",
        run=run or _runner(),
        lexists=lambda path: path in present,
        stat=lambda path: SimpleNamespace(st_mode=0o040000 | home_mode),
        mounts_text=mounts,
        polkit_rules=STOCK_POLKIT if polkit is None else polkit,
    )


def _failed(report):
    return {c["check"] for c in report["checks"] if not c["ok"]}


def test_isolated_guest_passes():
    report = _report()
    assert report["isolated"] is True
    assert _failed(report) == set()


def test_desktop_sudo_rights_fail():
    report = _report(run=_runner(sudo="    (ALL) NOPASSWD: ALL"))
    assert _failed(report) == {"desktop user has no sudo"}


def test_admin_group_membership_fails():
    # The stock polkit rule granting wheel then applies to the desktop user too.
    report = _report(run=_runner(groups="bluefin-test wheel"))
    assert _failed(report) == {"desktop user in no admin group",
                               "no polkit rule grants the desktop user"}


def test_usable_password_fails():
    report = _report(run=_runner(shadow="bluefin-test:$6$salt$hash:19000:0:99999:7:::"))
    assert _failed(report) == {"desktop password locked"}


def test_desktop_ssh_key_fails():
    # sshd's default AuthorizedKeysFile would admit it too.
    report = _report(keys=["/var/home/bluefin-test/.ssh/authorized_keys"])
    assert _failed(report) == {"desktop user has no SSH key",
                               "sshd admits no key for the desktop user"}


def test_readable_harness_home_fails():
    report = _report(home_mode=0o755)
    assert _failed(report) == {"harness home closed to others"}


@pytest.mark.parametrize("fstype", ["9p", "virtiofs"])
def test_host_shared_mount_fails(fstype):
    report = _report(mounts=f"hostshare /mnt/host {fstype} rw 0 0\n")
    assert _failed(report) == {"no host-shared mounts"}


@pytest.mark.parametrize("socket", ["/run/podman/podman.sock", "/run/libvirt/libvirt-sock",
                                    "/var/run/libvirt/libvirt-sock"])
def test_management_socket_fails(socket):
    report = _report(sockets=[socket])
    assert _failed(report) == {"no container or VM management sockets"}


@pytest.mark.parametrize("group", ["disk", "docker", "libvirt", "kvm", "systemd-journal", "adm",
                                   "sudo", "admin"])
def test_each_privileged_group_fails(group):
    report = _report(run=_runner(groups=f"bluefin-test {group}"))
    assert "desktop user in no admin group" in _failed(report)


def test_polkit_rule_naming_the_desktop_user_fails():
    rules = dict(STOCK_POLKIT)
    rules["/etc/polkit-1/rules.d/10-test.rules"] = (
        'polkit.addRule(function(a, s) { if (s.user == "bluefin-test") return polkit.Result.YES; });')
    assert _failed(_report(polkit=rules)) == {"no polkit rule grants the desktop user"}


def test_polkit_rule_granting_a_desktop_group_fails():
    rules = dict(STOCK_POLKIT)
    rules["/etc/polkit-1/rules.d/10-test.rules"] = (
        "polkit.addRule(function(a, s) { if (s.isInGroup('testers')) return polkit.Result.YES; });")
    report = _report(run=_runner(groups="bluefin-test testers"), polkit=rules)
    assert _failed(report) == {"no polkit rule grants the desktop user"}


def test_polkit_rule_without_yes_is_ignored():
    rules = {"/etc/polkit-1/rules.d/10-deny.rules":
             'polkit.addRule(function(a, s) { if (s.user == "bluefin-test") return polkit.Result.NO; });'}
    assert _failed(_report(polkit=rules)) == set()


def test_unreadable_polkit_rule_fails_closed():
    report = _report(polkit={"/etc/polkit-1/rules.d/10-test.rules": None})
    assert _failed(report) == {"no polkit rule grants the desktop user"}


def test_read_polkit_rules_reads_rules_files_only(tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "10-a.rules").write_text("A")
    (etc / "README").write_text("ignored")
    rules = iso.read_polkit_rules(dirs=(str(etc), str(tmp_path / "missing")))
    assert rules == {str(etc / "10-a.rules"): "A"}


def test_sshd_authorized_keys_command_fails():
    run = _runner(sshd=(0, SSHD_DEFAULT.replace("authorizedkeyscommand none",
                                                 "authorizedkeyscommand /usr/libexec/keys %u")))
    assert _failed(_report(run=run)) == {"sshd admits no key for the desktop user"}


def test_sshd_shared_keys_file_for_desktop_user_fails():
    run = _runner(sshd=(0, "authorizedkeysfile /etc/ssh/keys/%u\nauthorizedkeyscommand none\n"))
    report = _report(run=run, keys=["/etc/ssh/keys/bluefin-test"])
    assert _failed(report) == {"sshd admits no key for the desktop user"}


def test_sshd_config_check_fails_closed():
    run = _runner(sshd=(255, "sshd: no hostkeys available -- exiting."))
    assert _failed(_report(run=run)) == {"sshd admits no key for the desktop user"}


def test_missing_accounts_fail_closed():
    def run(cmd):
        return 2, ""
    report = _report(run=run)
    assert report["isolated"] is False
    assert {"desktop account exists", "harness account exists"} <= _failed(report)


# ── gnome-e2e action and canary wiring ────────────────────────────────────


def _action():
    return yaml.safe_load(ACTION.read_text())


def _step(name):
    return next(s for s in _action()["runs"]["steps"] if s["name"] == name)


def test_isolated_session_is_opt_in_and_forced_for_extensions():
    assert _action()["inputs"]["isolated-session"]["default"] == "false"
    keypair = _step("Generate SSH keypair")
    assert keypair["env"]["GNOME_E2E_ISOLATED_INPUT"] == "${{ inputs.isolated-session }}"
    assert '"${GNOME_E2E_SUITE}" == "extensions"' in keypair["run"]
    assert "GNOME_E2E_SSH_USER=gnome-e2e-harness" in keypair["run"]
    assert "GNOME_E2E_SSH_USER=bluefin-test" in keypair["run"]


def test_isolated_disk_uses_separate_accounts_and_shared_mode_is_kept():
    run = _step("Install OCI image and configure disk")["run"]
    isolated, _, shared = run.partition("guest_accounts.py")[2].partition("else")
    assert '--pubkey /tmp/gnome_e2e_key.pub' in isolated
    # Other suites keep their single account with key and sudo.
    assert "bluefin-test ALL=(ALL) NOPASSWD:ALL" in shared
    assert "AutomaticLogin=bluefin-test" in run


def test_isolation_is_proven_before_any_test_runs():
    run = _step("Install Python test stack")["run"]
    isolated = run.partition('if [[ "${GNOME_E2E_ISOLATED}" == "true" ]]; then')[2].partition("\nfi\n")[0]
    assert "guest_session_isolation.py" in isolated
    assert "> session-isolation.json || ISOLATION_RC=$?" in isolated
    assert "exit 1" in isolated
    # The checker runs as root from the harness home, never from a path the
    # desktop session can write.
    assert '$HOME/gnome_e2e_admin/guest_session_isolation.py' in isolated
    assert "/tmp/gnome_e2e/" not in isolated


def test_isolated_behave_runs_as_desktop_user_without_qecore_headless():
    run = _step("Run behave via qecore-headless")["run"]
    isolated = run.partition('if [[ "${GNOME_E2E_ISOLATED}" == "true" ]]; then')[2].partition("\nelse\n")[0]
    assert "sudo -u bluefin-test -H -- env -i" in isolated
    assert "$HOME/.local/bin/qecore-headless" not in isolated
    assert 'mkdir -m 0755 /tmp/gnome_e2e &&' in isolated
    assert "sudo chown -hR bluefin-test:bluefin-test /tmp/gnome_e2e" in isolated
    assert "-D disposable_guest=true" in isolated


def test_canary_passes_isolation_through_and_keeps_its_evidence():
    workflow = yaml.safe_load(CANARY.read_text())
    triggers = workflow[True]
    for trigger in ("workflow_dispatch", "workflow_call"):
        isolated = triggers[trigger]["inputs"]["isolated_session"]
        assert isolated["type"] == "boolean" and isolated["default"] is False
    steps = workflow["jobs"]["canary"]["steps"]
    action = next(s for s in steps if s.get("uses", "").endswith("/gnome-e2e"))
    assert action["with"]["isolated-session"] == "${{ inputs.isolated_session && 'true' || 'false' }}"
    collect = next(s for s in steps if s["name"] == "Collect guest journal and stop VM")
    assert 'GUEST_USER="${GNOME_E2E_SSH_USER:-bluefin-test}"' in collect["run"]
    assert "bluefin-test@127.0.0.1" not in collect["run"]
    upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert "session-isolation.json" in upload["with"]["path"]


def test_every_guest_ssh_in_the_action_uses_the_exported_account():
    assert "bluefin-test@127.0.0.1" not in ACTION.read_text()


def test_accounts_cli_reports_failure_as_an_error(tmp_path, capsys):
    deploy, var, _, _ = _guest(tmp_path)
    key = tmp_path / "key.pub"
    key.write_text("")
    assert guest_accounts.main([str(deploy), str(var), "--pubkey", str(key)]) == 1
    assert "::error::cannot provision isolated guest accounts" in capsys.readouterr().err


@pytest.mark.parametrize("isolated,rc", [(True, 0), (False, 1)])
def test_isolation_cli_exit_code_follows_the_report(monkeypatch, capsys, isolated, rc):
    report = {"isolated": isolated, "checks": [
        {"check": "desktop user has no sudo", "ok": isolated, "detail": "x"}]}
    monkeypatch.setattr(iso, "build_report", lambda desktop, harness: report)
    assert iso.main([]) == rc
    out = capsys.readouterr()
    assert '"isolated"' in out.out
    assert ("::error::session isolation" in out.err) is not isolated
