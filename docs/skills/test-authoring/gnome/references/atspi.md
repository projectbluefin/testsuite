---
name: atspi
description: "dogtail and AT-SPI lookup patterns and retry discipline."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Atspi

## dogtail 4.16 API

`requireResult` was removed from `findChild` in 4.16. Patterns:

```python
# no-raise presence check
nodes = app.findChildren(GenericPredicate(name="Settings"))

# fast-fail (raises immediately if not found)
node = app.findChild(GenericPredicate(name="Settings"), retry=False)

# WRONG — crashes at runtime
node = app.findChild(pred, requireResult=False)  # ← do not use
```
## AT-SPI lookup retry ownership

Use one monotonic elapsed-time deadline for the complete lookup. Each polling attempt
uses a single-shot application snapshot (`tree.root.applications()`) and no-raise
`findChildren` discovery; `tree.root.application(name)` has its own default retries,
so calling it for every alias inside a poll loop multiplies the declared timeout.

**Standalone app lookup pattern:**

```python
import time
from time import sleep

def _myapp_app(timeout: float = 15):
    """Find the app within one elapsed-time polling budget."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for app in tree.root.applications():
            if app.name in MYAPP_APP_NAMES:
                return app
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sleep(min(0.5, remaining))
    raise AssertionError(f"MyApp application was not found via AT-SPI after {timeout}s")
```

In `gnome_apps_steps.py`, `_app()` deliberately performs only one snapshot: its
caller `_wait_for_window()` owns retries for both application registration and visible
window discovery. `_wait_for_window_or_title()` checks the strict title fallback on
each poll under that same deadline, rather than starting a second full timeout.
Missing, hidden, or nonmatching windows still fail; delayed matching windows may succeed
before the deadline. Sleep is capped to the remaining budget. An in-flight native
AT-SPI/D-Bus call cannot be preempted by this deadline; no library retry is added on top.

A scenario-level `@retry` tag does not replace helper polling: it re-launches the
whole scenario and may open another app instance. Use it only for infrastructure
flakiness, not application registration lag.


When scaffolding multiple feature areas at once:
- One agent per feature area, all in parallel
- Each agent needs: feature file path, steps file path, a reference feature to follow, dogtail API constraints, the duplicate-step check command
- After swarm completes, always validate:

```bash
python3 -m py_compile tests/<suite>/features/steps/*.py
grep -h "^@step" tests/<suite>/features/steps/*.py | sort | uniq -d
```
