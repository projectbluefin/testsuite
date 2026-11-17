"""Behavioural contract tests for ``scripts/compose-e2e-image.sh``.

The script is the only thing standing between the raw image under test and the
composed image every E2E suite job actually boots. It runs exclusively inside
``e2e.yml``, so a regression in it is invisible until a full E2E lane fails —
and the failure reads like a product regression rather than a tooling bug.

Like ``test_install_kde_webdriver.py``, these tests *execute* the script inside
a hermetic sandbox rather than grepping its source. Text assertions cannot tell
a live guard from a dead one: grepping for ``--build-arg BASE_IMAGE`` still
passes if the value handed to it is the composed ref instead of the base ref,
and grepping for ``podman push`` still passes if the push runs before the build
or on a build that failed.

The sandbox gives the script:

* a fake ``PATH`` containing a ``podman`` shim that records its argv and returns
  a scripted exit code, so ``PODMAN=podman`` avoids needing real ``sudo``,
* a throwaway overlay directory supplied via ``E2E_OVERLAY_DIR``, so the real
  ``container/e2e-overlay`` build context is never built,
* no registry credentials of any kind — nothing here contacts ghcr.io.

Assertions are then made on observed behaviour: the exact argv podman received,
the ordering of build versus push, the exit codes of each guard, and the
contract that the composed ref is the final stdout line (``e2e.yml`` consumes
that line as the image to boot).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "compose-e2e-image.sh"

BASE_REF = "ghcr.io/projectbluefin/bluefin-lts:testing"
COMPOSED_REF = "ghcr.io/projectbluefin/testsuite/e2e:composed-1234"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None,
    reason="compose sandbox needs bash",
)


class ComposeRun:
    """Result of one sandboxed ``compose-e2e-image.sh`` execution."""

    def __init__(self, proc: subprocess.CompletedProcess, call_log: Path):
        self.proc = proc
        self._call_log = call_log

    @property
    def returncode(self) -> int:
        return self.proc.returncode

    @property
    def stdout(self) -> str:
        return self.proc.stdout

    @property
    def stderr(self) -> str:
        return self.proc.stderr

    @property
    def last_stdout_line(self) -> str:
        lines = [line for line in self.stdout.splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def calls(self) -> list[list[str]]:
        """Every recorded podman argv, in invocation order."""
        if not self._call_log.exists():
            return []
        recorded = []
        for line in self._call_log.read_text(encoding="utf-8").splitlines():
            if line:
                recorded.append(line.split("\x1f"))
        return recorded

    def podman_calls(self) -> list[list[str]]:
        """Recorded argv lists where podman itself was the executed binary."""
        return [argv for argv in self.calls() if argv and argv[0] == "podman"]

    def sudo_calls(self) -> list[list[str]]:
        """Recorded argv lists where the sudo shim was the executed binary."""
        return [argv for argv in self.calls() if argv and argv[0] == "sudo"]

    def subcommands(self) -> list[str]:
        """The podman subcommand of each podman call (``build``, ``push``)."""
        return [argv[1] for argv in self.podman_calls() if len(argv) > 1]

    def call(self, subcommand: str) -> list[str]:
        """The single recorded podman argv for ``subcommand``; fails if absent."""
        matches = [
            argv for argv in self.podman_calls() if len(argv) > 1 and argv[1] == subcommand
        ]
        assert matches, f"podman {subcommand} was never invoked: {self.calls()!r}"
        assert len(matches) == 1, f"podman {subcommand} invoked {len(matches)} times"
        return matches[0]


_RECORD = (
    'printf "%s" "$(basename "$0")" >> "$CALL_LOG"\n'
    'for arg in "$@"; do printf "\\x1f%s" "$arg" >> "$CALL_LOG"; done\n'
    'printf "\\n" >> "$CALL_LOG"\n'
)


@pytest.fixture
def sandbox(tmp_path: Path):
    """Return a callable that runs the script against fake podman + overlay."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "calls.log"

    def make_podman(build_rc: int = 0, push_rc: int = 0, emit_digest: bool = True) -> None:
        podman = bin_dir / "podman"
        digest_cmd = 'echo "sha256:1111111111111111111111111111111111111111111111111111111111111111" > "${arg#--digestfile=}" ;;' if emit_digest else ': ;;'
        podman.write_text(
            f"#!/bin/bash\n"
            f"{_RECORD}"
            f'case "$1" in\n'
            f"  build) exit {build_rc} ;;\n"
            f"  push)\n"
            f'    for arg in "$@"; do\n'
            f'      case "$arg" in\n'
            f'        --digestfile=*) {digest_cmd}\n'
            f'      esac\n'
            f'    done\n'
            f"    exit {push_rc} ;;\n"
            f"esac\n"
            f"exit 0\n",
            encoding="utf-8",
        )
        podman.chmod(0o755)

        sudo = bin_dir / "sudo"
        sudo.write_text(f'#!/bin/bash\n{_RECORD}exec "$@"\n', encoding="utf-8")
        sudo.chmod(0o755)

    def run(
        *args: str,
        overlay: Path | None = None,
        with_containerfile: bool = True,
        build_rc: int = 0,
        push_rc: int = 0,
        emit_digest: bool = True,
        podman_override: str | None = "podman",
        extra_env: dict[str, str] | None = None,
    ) -> ComposeRun:
        make_podman(build_rc=build_rc, push_rc=push_rc, emit_digest=emit_digest)
        overlay_dir = overlay if overlay is not None else tmp_path / "overlay"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        if with_containerfile:
            (overlay_dir / "Containerfile").write_text(
                "ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\n", encoding="utf-8"
            )

        env = {
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(tmp_path / "home"),
            "CALL_LOG": str(call_log),
            "E2E_OVERLAY_DIR": str(overlay_dir),
        }
        if podman_override is not None:
            env["PODMAN"] = podman_override
        if extra_env:
            env.update(extra_env)

        proc = subprocess.run(
            ["bash", str(SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
            timeout=60,
        )
        return ComposeRun(proc, call_log)

    run.overlay_root = tmp_path  # type: ignore[attr-defined]
    return run


def test_script_is_executable_bash() -> None:
    """CI invokes the script directly, so the bit and the shebang must hold."""
    assert SCRIPT.exists(), "scripts/compose-e2e-image.sh is missing"
    assert os.access(SCRIPT, os.X_OK), "compose-e2e-image.sh must stay executable"
    assert SCRIPT.read_text(encoding="utf-8").startswith("#!/bin/bash")


def test_missing_arguments_exit_2_without_touching_podman(sandbox) -> None:
    """A misuse must be a distinct exit code, not a half-composed image."""
    result = sandbox()
    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert result.calls() == []


def test_single_argument_exits_2(sandbox) -> None:
    """One ref is ambiguous — refusing beats guessing the composed name."""
    result = sandbox(BASE_REF)
    assert result.returncode == 2
    assert result.calls() == []


def test_extra_arguments_exit_2(sandbox) -> None:
    """A third arg means the caller's contract drifted; fail loudly."""
    result = sandbox(BASE_REF, COMPOSED_REF, "surprise")
    assert result.returncode == 2
    assert result.calls() == []


def test_missing_overlay_containerfile_exits_1(sandbox) -> None:
    """Without the overlay we would push the base image under a new name."""
    result = sandbox(BASE_REF, COMPOSED_REF, with_containerfile=False)
    assert result.returncode == 1
    assert "overlay Containerfile not found" in result.stderr
    assert result.calls() == []


def test_build_receives_base_image_as_build_arg(sandbox) -> None:
    """BASE_IMAGE must be the *base* ref — swapping it silently self-references."""
    result = sandbox(BASE_REF, COMPOSED_REF)
    assert result.returncode == 0
    argv = result.call("build")
    assert "--build-arg" in argv
    assert argv[argv.index("--build-arg") + 1] == f"BASE_IMAGE={BASE_REF}"


def test_build_tags_and_targets_the_composed_ref(sandbox) -> None:
    """``-t`` must carry the composed ref, and only the composed ref."""
    result = sandbox(BASE_REF, COMPOSED_REF)
    argv = result.call("build")
    assert argv[argv.index("-t") + 1] == COMPOSED_REF


def test_build_uses_overlay_containerfile_and_context(sandbox, tmp_path: Path) -> None:
    """The overlay dir is both the Containerfile source and the build context."""
    overlay = tmp_path / "custom-overlay"
    result = sandbox(BASE_REF, COMPOSED_REF, overlay=overlay)
    argv = result.call("build")
    assert argv[argv.index("-f") + 1] == str(overlay / "Containerfile")
    assert argv[-1] == str(overlay), "last build arg must be the build context"


def test_e2e_overlay_dir_override_is_honoured(sandbox, tmp_path: Path) -> None:
    """e2e.yml relies on the override to point at a non-default context."""
    overlay = tmp_path / "elsewhere" / "overlay"
    result = sandbox(BASE_REF, COMPOSED_REF, overlay=overlay)
    assert result.returncode == 0
    assert str(overlay) in result.call("build")


def test_push_sends_the_composed_ref(sandbox) -> None:
    """The pushed ref is what suite jobs boot; it must match the tag built."""
    result = sandbox(BASE_REF, COMPOSED_REF)
    argv = result.call("push")
    assert any(arg.startswith("--digestfile=") for arg in argv)
    assert argv[-1] == COMPOSED_REF

def test_build_runs_before_push(sandbox) -> None:
    """Pushing first would publish a stale tag from a previous run."""
    result = sandbox(BASE_REF, COMPOSED_REF)
    assert result.subcommands() == ["build", "push"]


def test_failed_build_aborts_before_push(sandbox) -> None:
    """``set -e`` must hold: a broken overlay may not reach the registry."""
    result = sandbox(BASE_REF, COMPOSED_REF, build_rc=7)
    assert result.returncode != 0
    assert "push" not in result.subcommands()


def test_failed_push_is_not_swallowed(sandbox) -> None:
    """A push failure must fail the job, not print a ref nothing can pull."""
    result = sandbox(BASE_REF, COMPOSED_REF, push_rc=3)
    assert result.returncode != 0
    assert result.last_stdout_line != COMPOSED_REF


def test_composed_ref_is_the_last_stdout_line(sandbox) -> None:
    """e2e.yml reads the final stdout line as the image to boot."""
    result = sandbox(BASE_REF, COMPOSED_REF)
    assert result.returncode == 0
    assert result.last_stdout_line == COMPOSED_REF


def test_log_lines_are_prefixed_and_never_the_last_line(sandbox) -> None:
    """Progress logging must not contaminate the machine-read final line."""
    result = sandbox(BASE_REF, COMPOSED_REF)
    logs = [line for line in result.stdout.splitlines() if line.startswith("[compose-e2e-image]")]
    assert logs, "script should log its progress"
    assert not result.last_stdout_line.startswith("[compose-e2e-image]")


def test_podman_override_is_word_split_for_wrapper_commands(sandbox, tmp_path: Path) -> None:
    """``PODMAN`` defaults to ``sudo podman``, so it must expand as words."""
    wrapper = tmp_path / "bin" / "fakesudo"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text('#!/bin/bash\nexec "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)

    result = sandbox(BASE_REF, COMPOSED_REF, podman_override="fakesudo podman")
    assert result.returncode == 0, result.stderr
    assert result.subcommands() == ["build", "push"]


def test_default_podman_is_sudo_podman(sandbox) -> None:
    """e2e.yml pulls into the root store; dropping sudo breaks that handoff."""
    result = sandbox(BASE_REF, COMPOSED_REF, podman_override=None)
    assert result.returncode == 0, result.stderr
    sudo_argv = result.sudo_calls()
    assert sudo_argv, "with no PODMAN override the script must go through sudo"
    assert [argv[1] for argv in sudo_argv] == ["podman", "podman"]
    assert [argv[2] for argv in sudo_argv] == ["build", "push"]


def test_refs_with_shell_metacharacters_are_not_expanded(sandbox) -> None:
    """Refs come from workflow inputs; unquoted expansion would be injectable."""
    weird_composed = "ghcr.io/projectbluefin/testsuite/e2e:pr-1$(id -u) *"
    result = sandbox(BASE_REF, weird_composed)
    assert result.returncode == 0
    argv = result.call("build")
    assert argv[argv.index("-t") + 1] == weird_composed
    assert result.call("push")[-1] == weird_composed


def test_push_fails_when_digest_is_missing(sandbox) -> None:
    """A push that produces an invalid/missing digest must fail the script."""
    result = sandbox(BASE_REF, COMPOSED_REF, emit_digest=False)
    assert result.returncode != 0
    assert "invalid or missing digest" in result.stderr


def test_push_emits_digest_and_pinned_image_outputs(sandbox, tmp_path: Path) -> None:
    """When GITHUB_OUTPUT is set, the script must write digest and name@digest."""
    out_file = tmp_path / "github_output"
    result = sandbox(BASE_REF, COMPOSED_REF, extra_env={"GITHUB_OUTPUT": str(out_file)})
    assert result.returncode == 0
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "digest=sha256:1111111111111111111111111111111111111111111111111111111111111111\n" in content
    expected_pinned = f"pinned_image={COMPOSED_REF.split(':')[0]}@sha256:1111111111111111111111111111111111111111111111111111111111111111\n"
    assert expected_pinned in content
    assert ":run-" not in content.split("pinned_image=")[1]
