---
name: top-bar
description: "Top-bar interactions and Shell.Eval parsing on GNOME 50+."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Top Bar

## GNOME Shell 50+ top-bar

AT-SPI nodes for clock and system-status have `INT_MIN` position — coordinate-based clicks are unreliable. Use `Shell.Eval` for:
- Overview toggle
- Quick-settings panel
- Date/calendar menu

```python
from tests.shared.gnome_shell_steps import _shell_eval

# qecore's context.sandbox.shell is an AT-SPI Accessible, not a JS bridge.
# Drive Shell.Eval with gdbus via the shared helper instead.
_shell_eval("Main.panel.statusArea.quickSettings.menu.open()")
```

`gdbus` equivalent:
```bash
gdbus call --session \
  --dest org.gnome.Shell \
  --object-path /org/gnome/Shell \
  --method org.gnome.Shell.Eval \
  "global.context.unsafe_mode = true"
```
## Shell.Eval via gdbus — critical parsing rule

`gdbus call` always returns `(success_bool, 'js_result')`. The success flag
is **always** `true` when the Eval method itself runs — even if the JS result
is `false`. **Never use `'true' in out`** to check a boolean JS result:

```python
# WRONG — always True because gdbus wraps result as (true, 'false')
assert 'true' in out.lower()

# CORRECT — extract the JS result (second tuple element)
import re
m = re.search(r",\s*'(true|false)'\s*\)", out, re.IGNORECASE)
result = m.group(1).lower() == 'true'  # True only if JS returned true
```

Use the `_eval_bool(js)` / `_wait_eval_bool(js, expected)` helpers from
`tests/smoke/features/steps/steps.py` rather than hand-rolling this.

### Avoid local re-definitions of `_shell_eval`
**CRITICAL**: Never define local/duplicate versions of `_shell_eval` or `_eval_bool` (such as in `vanilla-gnome/features/steps/steps.py`). Always import and reuse the shared helper from `tests.shared.gnome_shell_steps`. 
*Why:* GNOME 50 resets `unsafe_mode` to `false` aggressively after almost any UI event (modal dialogs, menus, overview toggle). The shared `_shell_eval` is specifically engineered to prepended `global.context.unsafe_mode = true` on every single invocation, whereas local hand-rolled versions that omit this will immediately fail on subsequent steps.
## Overview open/closed detection

**Do not** use AT-SPI `n.name.lower() == "overview"` — the node name varies
across GNOME versions. Use Shell.Eval instead:

```python
# Reliable across GNOME 45–50
_wait_eval_bool('Main.overview.visible.toString()', expected=True)
```
## Quick Settings DND property drift

GNOME Shell has exposed the Do Not Disturb toggle under multiple private names:
- `_doNotDisturb`
- `_do_not_disturb`
- `_dnd`

Smoke helpers should resolve all known aliases before touching `.checked` or
`.toggle()`. If no quick-settings object exists, fall back to the canonical
`org.gnome.desktop.notifications show-banners` gsettings key.

**GNOME 50 caveat**: `quickSettings._doNotDisturb` may exist as an object but
`.checked` is not accessible (TypeError). `_dnd_toggle_exists_js()` must
verify `?.checked !== undefined` (not just `!== null`) to trigger the
gsettings fallback correctly. The test in steps.py:

```python
def _dnd_toggle_exists_js() -> str:
    return f"({_DND_TOGGLE_JS})?.checked !== undefined"
```

## Overview search entry

**Do not** call `Main.overview._onSearchChanged()` — it was removed in GNOME 47.
Use `clutter_text.set_text()` which emits the `text-changed` signal and
triggers the search controller via the public signal path:

```python
_shell_eval(f'Main.overview.searchEntry.clutter_text.set_text("{text}")')
```

To read back the current search text:
```python
_shell_eval('Main.overview.searchEntry.clutter_text.get_text()')
# returns: (true, 'Files')  — parse with regex on the second element
```

## Activities overview (GNOME 50 QEMU)

`Main.overview.visible.toString()` consistently returns `false` in QEMU on GNOME 50
even after `Main.overview.show()` is called. Do NOT assert `Main.overview.visible` or
switch to `Main.overview._shown` without confirming on a live GNOME 50 QEMU run —
the behavior is not reproducible locally without a full VM boot. Scenarios that depend
on overview visibility must be quarantined (`@quarantine`) until the correct GNOME 50
API is confirmed.
