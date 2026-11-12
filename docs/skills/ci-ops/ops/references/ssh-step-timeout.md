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

## A command that forks a background child hangs to the timeout

`ssh` doesn't return until every process holding the remote channel's stdin,
stdout or stderr has let go. A command that forks a long-lived child, for
example `wl-copy` (its child keeps serving the clipboard selection), passes
all three to the child, so the step waits for the full timeout even though
the command itself finished (#1126, #1164).

Detach every stream the child could inherit. When the input is the payload,
drain it into a guest file first and give the command that file:

```sh
f=$(mktemp); err=$(mktemp); cat >"$f"
wl-copy <"$f" >/dev/null 2>"$err"
```

See `_clipboard_set` in `tests/smoke/features/steps/bluefin_new_extensions_steps.py`.

---
