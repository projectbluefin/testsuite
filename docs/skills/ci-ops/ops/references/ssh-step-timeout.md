---
name: ssh-step-timeout
description: "Deep dive: SSH step timeout"
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Ssh Step Timeout

## SSH step timeout

Default `run_ssh()` timeout is **60 seconds**, not 30. Hardware commands (bootc upgrade, disk ops) are slow in emulated VMs.

```python
run_ssh(context, "sudo bootc upgrade", timeout=180)
```

Never lower the default below 60s.

---

## A step that stops at exactly its timeout may be waiting on the desktop

A step that always fails at exactly its timeout usually has a command that
is waiting for something, not one that is slow. Find out what it waits for
before changing how the command is fed.

`wl-copy` and `wl-paste` are the known case (#1164). GNOME advertises no
Wayland data-control protocol: a `WAYLAND_DEBUG=1` run on Utah saw only
`wl_data_device_manager`, `zwp_primary_selection_device_manager_v1` and
`wl_seat`. Without one, `wl-copy` maps a 1x1 surface and waits for keyboard
focus, which GNOME never gives a background client. Draining its stdin into
a file first (#1183's first attempt) changed nothing.

Set and read the clipboard inside GNOME Shell instead, with `St.Clipboard`
through `Shell.Eval`. See `_clipboard_set` and `_clipboard_get` in
`tests/smoke/features/steps/bluefin_new_extensions_steps.py`.

---
