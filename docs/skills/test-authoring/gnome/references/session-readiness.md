---
name: session-readiness
description: "Session readiness across a GDM restart in containerized tests."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Session readiness across a GDM restart

`qecore-headless` restarts GDM, which destroys the session D-Bus socket and
brings up a fresh autologin session. `tests/shared/wait_for_shell.py` is the
canonical readiness helper and encodes the resulting contract:

- `ServiceUnknown` (bus up, `org.gnome.Shell` unowned) and
  `Could not connect: No such file or directory` (socket gone, GDM restarting)
  are **both retryable**, never terminal.
- The session bus address is **re-resolved on every attempt**
  (`resolve_session_bus_env()`); an address or connection cached before the
  restart points at a destroyed socket and can never recover. The address is
  never *unset* — an empty `DBUS_SESSION_BUS_ADDRESS` sends `gdbus` down the
  `dbus-launch --autolaunch` path instead of the real session socket.
- Readiness must hold for two consecutive checks so a check does not latch onto
  the outgoing session moments before GDM tears it down.
- The loop is bounded by a 300s wall-clock deadline, and the timeout message
  reports a per-error-class attempt breakdown plus the last error.
- When the socket file is absent the probe short-circuits instead of spawning
  `gdbus`, because an unreachable/empty address sends GIO down the
  `dbus-launch --autolaunch` path, which cannot work in the test container.
- `collect_session_diagnostics()` snapshots socket presence, `loginctl
  list-sessions` and `systemctl status gdm` on the first failure, every 15th
  failure, and at timeout. If the socket never returns and no user session is
  listed, the fault is lane-side GDM provisioning, not this helper.

Reuse this helper rather than writing a new `gdbus`-poll loop. See
`docs/skills/ci-ops/ops/references/qecore-headless-restarts-gdm-bus-socket-churn.md`.
