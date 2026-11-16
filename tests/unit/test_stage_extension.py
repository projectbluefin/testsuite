"""Unit tests for scripts/stage_extension.py and its gnome-e2e wiring (#909).

Synthetic ZIPs stand in for the packed extension; ``chown`` is injected so the
tests run unprivileged. They prove the exact archive is checked against the
builder's hash and its contract before anything is written into the guest, and
that the action and workflow pass that hash through.
"""
import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts import stage_extension as stage
from tests.shared import gnome_extensions_artifacts as art

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / ".github/actions/gnome-e2e/action.yml"
WORKFLOW = ROOT / ".github/workflows/extension-validation.yml"
JP = art.find_contract("just-perfection-desktop@just-perfection")


def _zip(path: Path, uuid: str = JP.uuid, extra: dict | None = None, executable=()) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name in JP.required_paths:
            content = json.dumps({"uuid": uuid}) if name == "metadata.json" else f"// {name}\n"
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (0o755 if name in executable else 0o644)) << 16
            zf.writestr(info, content)
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _no_chown(calls):
    return lambda path, uid, gid: calls.append((Path(path), uid, gid))


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "var/home/bluefin-test"
    home.mkdir(parents=True)
    return home


def test_valid_zip_is_staged_with_its_profile_tag(tmp_path, home):
    archive = _zip(tmp_path / "jp.zip", executable={"extension.js"})
    calls = []
    report = stage.stage(archive, _sha(archive), home, 1001, 1001, chown=_no_chown(calls))
    target = home / ".local/share/gnome-shell/extensions" / JP.uuid
    assert report["staged"] is True
    assert report["profile"] == "just-perfection" and report["tag"] == "just_perfection"
    assert report["source_rev"] == JP.source_rev and report["zip_sha256"] == _sha(archive)
    assert report["guest_path"] == f"/var/home/bluefin-test/.local/share/gnome-shell/extensions/{JP.uuid}"
    assert report["files"] == len(JP.required_paths)
    for name in JP.required_paths:
        assert (target / name).is_file()
    assert json.loads((target / "metadata.json").read_text())["uuid"] == JP.uuid
    assert stat.S_IMODE((target / "extension.js").stat().st_mode) == 0o755
    assert stat.S_IMODE((target / "prefs.js").stat().st_mode) == 0o644
    # Every created path, directories included, goes to the desktop user.
    owned = {path for path, uid, gid in calls if (uid, gid) == (1001, 1001)}
    assert home / ".local" in owned and target in owned and target / "lib/Prefs/Prefs.js" in owned


def test_hash_mismatch_stages_nothing(tmp_path, home):
    archive = _zip(tmp_path / "jp.zip")
    with pytest.raises(stage.StagingError) as exc:
        stage.stage(archive, "0" * 64, home, 1001, 1001, chown=_no_chown([]))
    assert exc.value.category == art.CATEGORY_ARTIFACT
    assert not (home / ".local").exists()


@pytest.mark.parametrize("sha", ["", "abc", "g" * 64])
def test_missing_or_malformed_builder_hash_is_a_harness_failure(tmp_path, home, sha):
    archive = _zip(tmp_path / "jp.zip")
    with pytest.raises(stage.StagingError) as exc:
        stage.stage(archive, sha, home, 1001, 1001, chown=_no_chown([]))
    assert exc.value.category == art.CATEGORY_HARNESS


def test_missing_zip_is_a_harness_failure(tmp_path, home):
    with pytest.raises(stage.StagingError) as exc:
        stage.stage(tmp_path / "absent.zip", "0" * 64, home, 1001, 1001, chown=_no_chown([]))
    assert exc.value.category == art.CATEGORY_HARNESS


def test_unknown_uuid_is_a_metadata_failure(tmp_path, home):
    archive = _zip(tmp_path / "other.zip", uuid="other@example.com")
    with pytest.raises(stage.StagingError) as exc:
        stage.stage(archive, _sha(archive), home, 1001, 1001, chown=_no_chown([]))
    assert exc.value.category == art.CATEGORY_METADATA


def test_incomplete_package_is_an_artifact_failure(tmp_path, home):
    archive = tmp_path / "jp.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("metadata.json", json.dumps({"uuid": JP.uuid}))
    with pytest.raises(stage.StagingError) as exc:
        stage.stage(archive, _sha(archive), home, 1001, 1001, chown=_no_chown([]))
    assert exc.value.category == art.CATEGORY_ARTIFACT
    assert "missing required paths" in str(exc.value)
    assert "resources.gresource" in str(exc.value)


def test_unsafe_member_is_refused_before_extraction(tmp_path, home):
    archive = _zip(tmp_path / "jp.zip", extra={"../escape.js": "x"})
    with pytest.raises(stage.StagingError) as exc:
        stage.stage(archive, _sha(archive), home, 1001, 1001, chown=_no_chown([]))
    assert exc.value.category == art.CATEGORY_ARTIFACT
    assert not (tmp_path / "var/home/escape.js").exists() and not (home / ".local").exists()


def test_existing_install_means_the_guest_is_not_fresh(tmp_path, home):
    archive = _zip(tmp_path / "jp.zip")
    (home / ".local/share/gnome-shell/extensions" / JP.uuid).mkdir(parents=True)
    with pytest.raises(stage.StagingError, match="not fresh") as exc:
        stage.stage(archive, _sha(archive), home, 1001, 1001, chown=_no_chown([]))
    assert exc.value.category == art.CATEGORY_HARNESS


def test_symlink_in_staging_path_is_refused(tmp_path, home):
    archive = _zip(tmp_path / "jp.zip")
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / ".local").symlink_to(outside)
    with pytest.raises(stage.StagingError, match="symlink"):
        stage.stage(archive, _sha(archive), home, 1001, 1001, chown=_no_chown([]))
    assert list(outside.iterdir()) == []


def test_cli_records_failure_and_exits_nonzero(tmp_path, home, capsys):
    archive = _zip(tmp_path / "jp.zip")
    out = tmp_path / "results/extension-staging.json"
    rc = stage.main([str(archive), "--sha256", "0" * 64, "--home", str(home),
                     "--uid", str(os.getuid()), "--gid", str(os.getgid()), "--output", str(out)])
    assert rc == 1
    report = json.loads(out.read_text())
    assert report["staged"] is False and report["category"] == art.CATEGORY_ARTIFACT
    assert "::error::extension staging failed" in capsys.readouterr().err


def test_cli_stages_and_records_provenance(tmp_path, home):
    archive = _zip(tmp_path / "jp.zip")
    out = tmp_path / "results/extension-staging.json"
    rc = stage.main([str(archive), "--sha256", _sha(archive), "--home", str(home),
                     "--uid", str(os.getuid()), "--gid", str(os.getgid()), "--output", str(out)])
    assert rc == 0
    assert json.loads(out.read_text())["tag"] == "just_perfection"


# ── gnome-e2e action and workflow wiring ─────────────────────────────────


def _step(doc, name):
    return next(s for s in doc["runs"]["steps"] if s["name"] == name)


def test_action_inputs_default_empty_so_existing_callers_are_unchanged():
    inputs = yaml.safe_load(ACTION.read_text())["inputs"]
    assert inputs["extension-zip"]["default"] == ""
    assert inputs["extension-sha256"]["default"] == ""


def test_action_stages_before_boot_and_fails_after_cleanup():
    action = yaml.safe_load(ACTION.read_text())
    install = _step(action, "Install OCI image and configure disk")
    assert install["env"]["GNOME_E2E_EXTENSION_ZIP"] == "${{ inputs.extension-zip }}"
    assert install["env"]["GNOME_E2E_EXTENSION_SHA256"] == "${{ inputs.extension-sha256 }}"
    run = install["run"]
    staging = run.index("stage_extension.py")
    assert run.index("guest_accounts.py") < staging < run.index("sudo umount /mnt/root")
    assert '--sha256 "${GNOME_E2E_EXTENSION_SHA256}"' in run
    assert '--home "${VAR}/home/bluefin-test" --uid 1001 --gid 1001' in run
    assert run.index("sudo losetup -d") < run.index("if [[ ${STAGE_RC} -ne 0 ]]")


def test_action_compiles_schemas_and_records_shell_before_session_restart():
    run = _step(yaml.safe_load(ACTION.read_text()), "Install Python test stack")["run"]
    compile_at = run.index("glib-compile-schemas")
    assert "sudo -u bluefin-test sh -c" in run[compile_at - 200:compile_at]
    assert compile_at < run.index('$SSH "sudo systemctl stop gdm"')
    assert "results/guest-shell-version.txt" in run


def test_action_selects_and_gates_only_the_staged_extension():
    action = yaml.safe_load(ACTION.read_text())
    run = _step(action, "Run behave via qecore-headless")["run"]
    assert '--tags @${GNOME_E2E_EXTENSION_TAG}' in run
    gate = _step(action, "Gate extension-validation run")
    assert gate["env"]["GNOME_E2E_SUITE"] == "${{ inputs.suite }}"
    assert 'REQUIRE_TAG=(--require-tag "${GNOME_E2E_EXTENSION_TAG}")' in gate["run"]
    assert "No candidate extension was staged" in gate["run"]


def test_workflow_builds_offline_and_passes_the_recorded_hash():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow[True]) == {"workflow_dispatch"}
    steps = workflow["jobs"]["validate"]["steps"]
    names = [s["name"] for s in steps]
    harness = names.index("Build native harness over pinned official GNOME OS")
    build = names.index("Pack the extension from its pinned revision")
    run = names.index("Boot GNOME OS with the extension staged and run its scenarios")
    assert harness < build < run
    assert "--builder-image" in steps[build]["run"]
    lane = steps[run]["with"]
    assert lane["suite"] == "extensions"
    assert lane["extension-zip"] == "${{ steps.build.outputs.zip }}"
    assert lane["extension-sha256"] == "${{ steps.build.outputs.sha256 }}"
    assert "secrets." not in WORKFLOW.read_text()


def test_user_extensions_are_reallowed_after_the_harness_restarts_the_shell():
    # A Shell SIGKILLed by the GDM stop runs org.gnome.Shell-disable-extensions
    # (run 43609183896); the reset must come after the restart, before behave.
    action = yaml.safe_load(ACTION.read_text())
    run = _step(action, "Install Python test stack")["run"]
    restart = run.index('$SSH "sudo systemctl start gdm"')
    reallow = run.index("org.gnome.shell disable-user-extensions false")
    assert restart < reallow
    assert 'if [[ -n "${GNOME_E2E_EXTENSION_UUID:-}" ]]; then' in run[restart:reallow]
