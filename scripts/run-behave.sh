#!/bin/bash
# Thin launcher for the GNOME OS canary. qecore-headless (4.19.3) rebuilds
# behave's environment from the first gnome-session pid and keeps only
# PYTHONPATH/TEST/TERM/GNOME_ACCESSIBILITY/QECORE_* — so the SSH-sourced
# display, session bus, runtime dir and AT-SPI address went stale after the
# --unsafe-mode GDM restart. This wrapper runs after that restart, reads the
# live values, and execs behave. qecore requires the first word of the command
# to be an executable, so the action passes /bin/bash to qecore-headless.
set -euo pipefail
export PATH="/var/home/bluefin-test/.local/bin:/usr/local/bin:/usr/bin:/bin"
uid=$(id -u)
export XDG_RUNTIME_DIR=/run/user/$uid
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
eval "$(systemctl --user show-environment | grep -E '^(WAYLAND_DISPLAY|DISPLAY)=' | sed 's/^/export /')"
export AT_SPI_BUS_ADDRESS=$(busctl --user call org.a11y.Bus /org/a11y/bus org.a11y.Bus GetAddress | cut -d'"' -f2)
exec /var/home/bluefin-test/.local/bin/behave /tmp/gnome_e2e/tests/gnomeos-canary/features/ \
  --format json.pretty --outfile /tmp/gnome_e2e/results/results.json \
  --format pretty --outfile /tmp/gnome_e2e/results/results.txt \
  --format progress --no-capture
