"""#909 step 2: exact candidate packages are staged before GNOME Shell starts.

``scripts/extension_candidates.py`` validates each packed ZIP against its
canonical contract and extracts it into the isolated desktop user's own
extension directory on the mounted guest, before boot. The ``gnome-e2e``
action runs it for ``suite: extensions`` only, limits Behave to the staged
profiles' tags and makes the gate require every one of those scenarios.
"""
from __future__ import annotations

import json
import os
import stat
import time
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts import extension_candidates as candidates
from tests.shared import gnome_extensions_artifacts as artifacts

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / ".github/actions/gnome-e2e/action.yml"
WORKFLOW = ROOT / ".github/workflows/gnomeos-extensions.yml"
JP_UUID = "just-perfection-desktop@just-perfection"


def _jp_zip(path: Path, uuid: str = JP_UUID, extra: dict[str, bytes] | None = None,
            drop: str | None = None, date_time=(2026, 11, 14, 12, 0, 0)) -> Path:
    contract = artifacts.find_contract(JP_UUID)
    members = {name: b"// " + name.encode() for name in contract.required_paths}
    members["metadata.json"] = json.dumps({
        "uuid": uuid, "settings-schema": "org.gnome.shell.extensions.just-perfection",
    }).encode()
    members.update(extra or {})
    if drop:
        members.pop(drop)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("lib/", date_time=date_time), b"")
        for name, data in members.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=date_time), data)
    return path


def _home(tmp_path: Path) -> tuple[Path, dict]:
    home = tmp_path / "var/home/bluefin-test"
    home.mkdir(parents=True)
    owners: dict[Path, tuple[int, int]] = {}
    return home, owners


def _chown(owners):
    return lambda path, uid, gid: owners.__setitem__(Path(path), (uid, gid))


# ── plan ──────────────────────────────────────────────────────────────────


def test_plan_takes_the_revision_from_the_canonical_contract():
    planned = candidates.plan("just-perfection")
    contract = artifacts.find_contract(JP_UUID)
    assert planned["revision"] == contract.source_rev
    assert planned["repository"] == "gnome-extensions-hive/just-perfection"
    assert planned["package_command"] == "bash scripts/build.sh"
    assert planned["tag"] == "just_perfection"


@pytest.mark.parametrize("profile", ["sjc-gold", "shade-inactive-windows", "stock-market"])
def test_profiles_without_a_lane_recipe_fail_closed(profile):
    with pytest.raises(candidates.CandidateError, match="no packaging recipe"):
        candidates.plan(profile)


def test_unknown_profile_fails():
    with pytest.raises(candidates.CandidateError, match="unknown"):
        candidates.plan("dash-to-dock")


def test_plan_rejects_a_collection_repository_that_differs_from_the_contract():
    collection = candidates.load_collection()
    collection["just-perfection"]["repository"] = "someone/just-perfection"
    with pytest.raises(candidates.CandidateError, match="does not match"):
        candidates.plan("just-perfection", collection)


# ── validate ──────────────────────────────────────────────────────────────


def test_valid_candidate_records_its_identity(tmp_path):
    [record] = candidates.validate([_jp_zip(tmp_path / "jp.zip")])
    assert record["uuid"] == JP_UUID
    assert record["tag"] == "just_perfection"
    assert record["source_rev"] == artifacts.find_contract(JP_UUID).source_rev
    assert len(record["zip_sha256"]) == 64


def test_archive_missing_a_required_path_is_refused(tmp_path):
    zip_path = _jp_zip(tmp_path / "jp.zip", drop="resources.gresource")
    with pytest.raises(candidates.CandidateError, match=r"\[artifact\].*missing required paths: resources.gresource"):
        candidates.validate([zip_path])


def test_archive_without_a_contract_is_refused(tmp_path):
    zip_path = _jp_zip(tmp_path / "x.zip", uuid="other@example.com")
    with pytest.raises(candidates.CandidateError, match="no canonical contract"):
        candidates.validate([zip_path])


def test_the_same_extension_twice_is_refused(tmp_path):
    first = _jp_zip(tmp_path / "a.zip")
    second = _jp_zip(tmp_path / "b.zip")
    with pytest.raises(candidates.CandidateError, match="staged twice"):
        candidates.validate([first, second])


def test_no_archives_is_refused():
    with pytest.raises(candidates.CandidateError, match="no candidate"):
        candidates.validate([])


def test_unsafe_member_is_refused_before_staging(tmp_path):
    zip_path = _jp_zip(tmp_path / "jp.zip", extra={"../escape.js": b"x"})
    home, owners = _home(tmp_path)
    with pytest.raises(candidates.CandidateError, match="unsafe archive path"):
        candidates.stage(home, [zip_path], 1001, 1001, _chown(owners))
    assert not (home / ".local").exists()


# ── stage ─────────────────────────────────────────────────────────────────


def test_stage_extracts_into_the_desktop_users_extension_directory(tmp_path):
    home, owners = _home(tmp_path)
    [record] = candidates.stage(home, [_jp_zip(tmp_path / "jp.zip")], 1001, 1001, _chown(owners))
    dest = home / ".local/share/gnome-shell/extensions" / JP_UUID
    assert json.loads((dest / "metadata.json").read_text())["uuid"] == JP_UUID
    assert (dest / "lib/Prefs/PrefsKeys.js").is_file()
    assert record["staged_path"] == (
        "/var/home/bluefin-test/.local/share/gnome-shell/extensions/" + JP_UUID
    )
    assert record["files"] == len(artifacts.find_contract(JP_UUID).required_paths)
    # Every directory from .local down, and every file, belongs to the desktop user.
    for path in [home / ".local", dest, dest / "lib", dest / "extension.js"]:
        assert owners[path] == (1001, 1001)
    assert stat.S_IMODE(os.stat(dest / "extension.js").st_mode) == 0o644


def test_stage_refuses_a_symlink_in_the_extension_path(tmp_path):
    home, owners = _home(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / ".local").symlink_to(outside)
    with pytest.raises(candidates.CandidateError, match="symlink"):
        candidates.stage(home, [_jp_zip(tmp_path / "jp.zip")], 1001, 1001, _chown(owners))
    assert list(outside.iterdir()) == []


def test_stage_never_merges_into_an_existing_package(tmp_path):
    home, owners = _home(tmp_path)
    (home / ".local/share/gnome-shell/extensions" / JP_UUID).mkdir(parents=True)
    with pytest.raises(candidates.CandidateError, match="already exists"):
        candidates.stage(home, [_jp_zip(tmp_path / "jp.zip")], 1001, 1001, _chown(owners))


def test_stage_caps_the_expanded_size(tmp_path, monkeypatch):
    monkeypatch.setattr(candidates, "MAX_STAGED_BYTES", 64)
    home, owners = _home(tmp_path)
    zip_path = _jp_zip(tmp_path / "jp.zip", extra={"stylesheet.css": b"x" * 1024})
    with pytest.raises(candidates.CandidateError, match="expands past"):
        candidates.stage(home, [zip_path], 1001, 1001, _chown(owners))


def test_stage_cli_writes_provenance_and_tag_selection(tmp_path):
    home, _ = _home(tmp_path)
    provenance = tmp_path / "results/candidate-provenance.json"
    github_env = tmp_path / "github_env"
    # The real lchown, to this test's own ids (the action passes 1001).
    rc = candidates.main([
        "stage", "--home", str(home), "--provenance", str(provenance),
        "--uid", str(os.getuid()), "--gid", str(os.getgid()),
        "--github-env", str(github_env), str(_jp_zip(tmp_path / "jp.zip")),
    ])
    assert rc == 0
    [record] = json.loads(provenance.read_text())["candidates"]
    assert record["uuid"] == JP_UUID and record["pinned_zip_sha256"] is None
    assert github_env.read_text().splitlines() == [
        "GNOME_E2E_BEHAVE_TAGS=@just_perfection",
        "GNOME_E2E_REQUIRED_TAGS=just_perfection",
        f"GNOME_E2E_STAGED_UUIDS={JP_UUID}",
    ]


def test_stage_cli_reports_a_refusal_as_an_error(tmp_path, capsys):
    home, _ = _home(tmp_path)
    rc = candidates.main([
        "stage", "--home", str(home), "--provenance", str(tmp_path / "p.json"),
        str(_jp_zip(tmp_path / "x.zip", uuid="other@example.com")),
    ])
    assert rc == 1
    assert "::error::extension candidate" in capsys.readouterr().err
    assert not (tmp_path / "p.json").exists()


def test_behave_tags_join_profiles():
    assert candidates.behave_tags([{"tag": "sjc_gold"}, {"tag": "just_perfection"}]) == (
        "@just_perfection or @sjc_gold"
    )


# ── compare ───────────────────────────────────────────────────────────────


def test_compare_separates_timestamp_drift_from_content_changes(tmp_path):
    first = _jp_zip(tmp_path / "a.zip")
    time.sleep(0.01)
    second = _jp_zip(tmp_path / "b.zip", date_time=(2026, 11, 14, 12, 0, 4))
    report = candidates.compare(first, second)
    assert report["byte_identical"] is False
    assert report["content_identical"] is True
    changed = _jp_zip(tmp_path / "c.zip", extra={"extension.js": b"changed"})
    report = candidates.compare(first, changed)
    assert report["content_identical"] is False
    assert report["differing_members"] == ["extension.js"]
    assert candidates.compare(first, first)["byte_identical"] is True


# ── action and workflow wiring ────────────────────────────────────────────


def _step(name):
    action = yaml.safe_load(ACTION.read_text())
    return next(s for s in action["runs"]["steps"] if s["name"] == name)


def test_action_input_is_optional_and_extensions_only():
    action = yaml.safe_load(ACTION.read_text())
    assert action["inputs"]["extension-artifacts"]["default"] == ""
    install = _step("Install OCI image and configure disk")
    assert install["env"]["GNOME_E2E_EXTENSION_ARTIFACTS"] == "${{ inputs.extension-artifacts }}"
    guard = install["run"].partition("fallocate")[0]
    assert '"${GNOME_E2E_SUITE}" != "extensions"' in guard and "exit 1" in guard


def test_candidates_are_staged_before_boot_in_the_isolated_branch_only():
    run = _step("Install OCI image and configure disk")["run"]
    isolated = run.partition('if [[ "${GNOME_E2E_ISOLATED}" == "true" ]]; then')[2]
    isolated = isolated.partition("\n        else\n")[0]
    staging = isolated.partition("guest_accounts.py")[2]
    assert "extension_candidates.py stage" in staging
    assert '--home "${VAR}/home/bluefin-test"' in staging
    assert "extension_candidates.py" not in run.partition("\n        else\n")[2].partition("\n        fi\n")[0]
    # Before the disk is unmounted and the VM boots.
    assert run.index("extension_candidates.py stage") < run.index("sudo umount /mnt/root")


def test_schemas_are_compiled_as_the_desktop_user_before_the_test_login():
    run = _step("Install Python test stack")["run"]
    compile_at = run.index("glib-compile-schemas --strict")
    assert "sudo -u bluefin-test -H --" in run[run.rfind("\n", 0, compile_at):compile_at]
    assert compile_at < run.index('$SSH "sudo systemctl stop gdm"')


def test_run_is_limited_to_the_staged_profiles_and_the_gate_requires_them():
    run = _step("Run behave via qecore-headless")["run"]
    assert "--tags '${GNOME_E2E_BEHAVE_TAGS}'" in run
    gate = _step("Gate extension-validation run")["run"]
    assert '--require-tag "${tag}"' in gate
    assert 'python3 "${GATE}" results/results.json "${REQUIRED[@]}"' in gate


def test_workflow_builds_offline_and_stages_through_the_action():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow[True]["workflow_dispatch"]["inputs"]["extension"]["options"]) == {
        "just-perfection"
    }
    package = workflow["jobs"]["package"]
    build = next(s for s in package["steps"] if s["name"] == "Build the candidate twice, offline")
    assert "--network=none" in build["run"]
    validate = workflow["jobs"]["validate"]
    assert validate["needs"] == "package"
    action = next(s for s in validate["steps"] if s.get("uses") == "./.github/actions/gnome-e2e")
    assert action["with"]["suite"] == "extensions"
    assert action["with"]["extension-artifacts"] == "extension-candidate"
    for job in workflow["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04"
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False
