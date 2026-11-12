"""The canary must enable screenshot access without losing Shell's mode."""
import pytest

from scripts.configure_gnomeos_canary_shell import configure


@pytest.mark.parametrize("unit,arguments", [
    ("org.gnome.Shell@wayland.service", ""),
    ("org.gnome.Shell@.service", " --mode=%i"),
])
def test_preserves_pinned_service_command(tmp_path, unit, arguments):
    units = tmp_path / "usr/lib/systemd/user"
    units.mkdir(parents=True)
    executable = tmp_path / "usr/bin/gnome-shell"
    executable.parent.mkdir(parents=True)
    executable.touch()
    command = f"/usr/bin/gnome-shell{arguments}"
    original = f"[Service]\nType=notify\nExecStart={command}\nRestart=no\n"
    (units / unit).write_text(original)

    configure(tmp_path)

    assert (units / unit).read_text() == original
    dropin = units / f"{unit}.d/50-canary-unsafe-mode.conf"
    assert dropin.read_text() == f"[Service]\nExecStart=\nExecStart={command} --unsafe-mode\n"


@pytest.mark.parametrize("contents", [
    None, "[Service]\n", "ExecStart=/unknown/gnome-shell\n",
    "ExecStart=/usr/bin/gnome-shell\nExecStart=/usr/bin/another\n",
    "ExecStart=/usr/bin/gnome-shell\n",  # binary absent from image
])
def test_unknown_image_layout_fails(tmp_path, contents):
    units = tmp_path / "usr/lib/systemd/user"
    units.mkdir(parents=True)
    if contents is not None:
        (units / "org.gnome.Shell@.service").write_text(contents)
    with pytest.raises(ValueError):
        configure(tmp_path)
    assert not list(units.glob("*.d/*.conf"))
