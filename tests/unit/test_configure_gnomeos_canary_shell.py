"""The canary must enable screenshot access without losing Shell's mode."""
import pytest

from scripts.configure_gnomeos_canary_shell import (
    CANARY_SESSION_ENV, configure, write_canary_session_env,
)


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


REQUIRED_ENV_VARS = {
    "XDG_RUNTIME_DIR": "/run/user/1001",
    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1001/bus",
    "AT_SPI_BUS_ADDRESS": "unix:path=/run/user/1001/at-spi",
    "WAYLAND_DISPLAY": "wayland-0",
    "XDG_SESSION_TYPE": "wayland",
}


def test_write_canary_session_env_writes_dropin(tmp_path):
    write_canary_session_env(tmp_path)
    dropin = tmp_path / "var/home/bluefin-test/.config/environment.d/99-canary-session.conf"
    assert dropin.is_file()
    for name, value in REQUIRED_ENV_VARS.items():
        assert f"{name}={value}" in dropin.read_text()


def test_configure_writes_session_env_alongside_dropin(tmp_path):
    units = tmp_path / "usr/lib/systemd/user"
    units.mkdir(parents=True)
    (tmp_path / "usr/bin/gnome-shell").parent.mkdir(parents=True)
    (tmp_path / "usr/bin/gnome-shell").touch()
    (units / "org.gnome.Shell@.service").write_text(
        "[Service]\nType=notify\nExecStart=/usr/bin/gnome-shell\n")

    configure(tmp_path)

    dropin = tmp_path / "var/home/bluefin-test/.config/environment.d/99-canary-session.conf"
    assert dropin.is_file()
    for name, value in REQUIRED_ENV_VARS.items():
        assert f"{name}={value}" in dropin.read_text()


def test_session_env_is_stable_across_restart():
    # The runtime dir and bus/socket paths are recreated at fixed locations after a
    # GDM restart, so pinning them must not change between the outgoing and the new
    # session (that is exactly what makes the restarted shell carry them to behave).
    for name in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "AT_SPI_BUS_ADDRESS"):
        assert CANARY_SESSION_ENV.count(f"{name}=") == 1
