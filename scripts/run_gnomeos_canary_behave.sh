#!/usr/bin/env bash
set -euo pipefail

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
WAYLAND_DISPLAY=$(systemctl --user show-environment | sed -n 's/^WAYLAND_DISPLAY=//p')
: "${WAYLAND_DISPLAY:?No Wayland display in the user manager}"
export WAYLAND_DISPLAY XDG_SESSION_TYPE=wayland
AT_SPI_BUS_ADDRESS=$(gdbus call --session --dest org.a11y.Bus \
  --object-path /org/a11y/bus --method org.a11y.Bus.GetAddress |
  sed -n "s/^('\(unix:[^']*\)',)$/\1/p")
: "${AT_SPI_BUS_ADDRESS:?Could not discover the accessibility bus}"
export AT_SPI_BUS_ADDRESS
exec "$@"
