"""The harness build must refuse mismatched or substitute GNOME OS images."""
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "container/gnomeos-harness-identity.py"
GNOMEOS = 'ID=org.gnome.os\nNAME="GNOME OS"\nGNOMEOS_COMMIT=abc123\n'


def run(tmp_path, base, devel):
    (tmp_path / "base").write_text(base)
    (tmp_path / "devel").write_text(devel)
    return subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "base"), str(tmp_path / "devel")],
                          capture_output=True, text=True)


def test_matching_builds_pass(tmp_path):
    result = run(tmp_path, GNOMEOS, GNOMEOS + "VARIANT=devel\n")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("base,devel,message", [
    (GNOMEOS, GNOMEOS.replace("abc123", "def456"), "mismatch"),
    (GNOMEOS.replace("org.gnome.os", "fedora"), GNOMEOS, "not GNOME OS"),
    (GNOMEOS, GNOMEOS.replace("org.gnome.os", "fedora"), "not GNOME OS"),
    (GNOMEOS.replace("ID=org.gnome.os\n", ""), GNOMEOS, "not GNOME OS"),
    (GNOMEOS.replace("GNOMEOS_COMMIT=abc123\n", ""), GNOMEOS, "missing base commit"),
    (GNOMEOS.replace("abc123", ""), GNOMEOS.replace("abc123", ""), "missing base commit"),
    (GNOMEOS, GNOMEOS.replace("GNOMEOS_COMMIT=abc123\n", ""), "mismatch"),
])
def test_mismatched_or_substitute_builds_fail(tmp_path, base, devel, message):
    result = run(tmp_path, base, devel)
    assert result.returncode != 0
    assert message in result.stderr


def test_containerfile_has_no_heredoc_and_build_context_has_every_copy_source():
    # The canary runner's stock podman reads each heredoc line as an instruction.
    containerfile = (ROOT / "container/Containerfile.gnomeos-harness").read_text()
    assert "<<" not in containerfile
    build = (ROOT / "scripts/build-gnomeos-harness.sh").read_text()
    staged = set(re.findall(r'"\$CONTEXT/([^"]*)"', build))
    staged |= {Path(src).name for src in re.findall(r'^cp "\$REPO_ROOT/([^"]+)" "\$CONTEXT/"$', build, re.M)}
    sources = re.findall(r"^COPY (?!--from)(\S+) ", containerfile, re.M)
    assert "gnomeos-harness-identity.py" in sources
    assert set(sources) <= staged, set(sources) - staged
    assert "RUN python3 /tmp/gnomeos-harness-identity.py" in containerfile
