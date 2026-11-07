"""Custom step definitions for sudo-rs privilege escalation and security checks."""

from behave import step

from steps.steps import _run_host


@step("/usr/bin/sudo is owned by root and has setuid mode 4755")
def sudo_is_setuid_root_4755(context) -> None:
    output, returncode, stderr = _run_host("stat -c '%a %U:%G' /usr/bin/sudo")
    assert returncode == 0, f"stat on /usr/bin/sudo failed: {stderr or output}"
    mode, owner = output.split(maxsplit=1)
    assert mode == "4755", (
        f"/usr/bin/sudo has invalid mode '{mode}' (expected '4755'). "
        "BuildStream strip-binaries may have stripped the setuid bit."
    )
    assert owner == "root:root", f"/usr/bin/sudo owner is '{owner}' (expected 'root:root')"


@step("sudo -n id -u returns user ID 0")
def sudo_n_id_u_returns_0(context) -> None:
    current_uid, returncode, stderr = _run_host("id -u")
    assert returncode == 0, f"id -u failed: {stderr or current_uid}"
    assert current_uid != "0", "sudo escalation check must start as a non-root user"

    output, returncode, stderr = _run_host("sudo -n id -u")
    assert returncode == 0, f"sudo -n id -u failed (rc={returncode}): {stderr or output}"
    assert output == "0", f"Expected root UID 0 from sudo -n id -u, got '{output}'"


@step("sudo --preserve-env preserves specified environment variables")
def sudo_preserve_env_check(context) -> None:
    cmd = (
        "env TEST_SUDO_SCRUBBED=secret TEST_SUDO_PRESERVED=kept "
        "sudo -n --preserve-env=TEST_SUDO_PRESERVED env"
    )
    output, returncode, stderr = _run_host(cmd)
    assert returncode == 0, f"sudo --preserve-env execution failed: {stderr or output}"
    assert "TEST_SUDO_PRESERVED=kept" in output, (
        "Expected TEST_SUDO_PRESERVED to be retained in sudo environment"
    )
    assert "TEST_SUDO_SCRUBBED=" not in output, (
        "Expected TEST_SUDO_SCRUBBED to be scrubbed from sudo environment"
    )


@step("sudo PAM configuration references system-auth stack")
def sudo_pam_includes_system_auth(context) -> None:
    output, returncode, stderr = _run_host(
        r"""grep -Eq '^[[:space:]]*(auth|account|password|session)[[:space:]]+"""
        r"""(include|substack)[[:space:]]+system-auth([[:space:]]|$)' /etc/pam.d/sudo"""
    )
    assert returncode == 0, (
        f"/etc/pam.d/sudo does not include the system-auth stack: {stderr or output}"
    )


@step("sudoedit binary is present and operational")
def sudoedit_binary_check(context) -> None:
    path, returncode, stderr = _run_host("command -v sudoedit")
    assert returncode == 0, f"sudoedit binary not found on PATH: {stderr or path}"

    stat_out, returncode, stderr = _run_host(
        # sudoedit is a symlink to sudo on Dakota; check the binary it resolves to.
        "stat -L -c '%a %U:%G' \"$(command -v sudoedit)\""
    )
    assert returncode == 0, f"stat sudoedit failed: {stderr or stat_out}"
    mode, owner = stat_out.split(maxsplit=1)
    assert mode == "4755", f"sudoedit has invalid mode '{mode}' (expected '4755')"
    assert owner == "root:root", (
        f"sudoedit owner is '{owner}' (expected 'root:root')"
    )

    version, returncode, stderr = _run_host("sudoedit -V")
    assert returncode == 0, f"sudoedit -V failed: {stderr or version}"
    assert version, "sudoedit -V returned no version information"
