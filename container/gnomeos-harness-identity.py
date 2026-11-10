"""Refuse to build the harness unless base and devel are the same GNOME OS build.

Kept as a file instead of a Containerfile heredoc: the runner's stock podman
parses each heredoc line as a build instruction.
"""
import shlex
import sys
from pathlib import Path


def identity(path):
    return dict(line.split('=', 1) for line in shlex.split(Path(path).read_text(), comments=True))


def check(base_path, devel_path):
    base = identity(base_path)
    devel = identity(devel_path)
    assert base.get('ID') == devel.get('ID') == 'org.gnome.os', 'not GNOME OS'
    assert base.get('GNOMEOS_COMMIT'), 'missing base commit'
    assert base['GNOMEOS_COMMIT'] == devel.get('GNOMEOS_COMMIT'), 'base/devel build mismatch; retry after publication completes'


if __name__ == '__main__':
    check(*(sys.argv[1:] or ['/tmp/base-os-release', '/usr/lib/os-release']))
