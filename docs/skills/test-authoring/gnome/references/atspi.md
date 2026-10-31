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

Close waits ("X is no longer running") follow the same rule: each poll takes one
snapshot, keeps the apps whose names match, and checks them for a visible frame.
Do not fall back to a per-alias `tree.root.application(name)` or
`tree.root.findChild(pred, recursive=False, retry=False)`. The first retries for
seconds per missing alias. The second raises `TypeError` on the dogtail 2.0.3 the
VMs install (`findChild(self, predicate, retry=True)` has no `recursive`), and a
blanket `except` then turns that into a false "closed". `MagicMock` roots hide both
problems, so timing tests should use a fake root with dogtail 2.0.3's real
signatures and a fake clock (see `_Dogtail203Root` in
`tests/unit/test_gnome_files_steps.py`).

A scenario-level `@retry` tag does not replace helper polling: it re-launches the
whole scenario and may open another app instance. Use it only for infrastructure
flakiness, not application registration lag.

## Bazaar (GTK4 Flatpak)

Source-backed facts used by `tests/software/features/steps/steps.py`:

- **Application name `bazaar`.** GTK4's AT-SPI root reports `g_get_prgname()`
  (`gtk/a11y/gtkatspiroot.c`). `g_application_run()` sets that name to
  `basename(argv[0])`, and `bazaar-daemon` execs `/app/bin/bazaar`. The old
  aliases `gnome-software`, `org.gnome.Software` and `Bazaar` never matched.
  `_bazaar_app()` called `tree.root.application()` for each of them inside an
  iteration-counted loop, which kept software run 41182977349 searching from
  08:20 until it was cancelled at 10:03.
- **Window.** The main window is a `frame` named `Bazaar` that is a direct child
  of the app. The title becomes `Bazaar — <page>` only on pushed pages.
- **Views.** libadwaita exposes each `AdwViewStackPage` as a `panel` labelled
  with its title (`Curated`, `Explore`, `Library`, `Search`). Only the visible
  page has showing widgets. The header-bar tabs (`page tab`, or `toggle button`
  on older libadwaita) stay showing behind the **Refreshing** page, so "the tab
  exists plus any showing widget" passes before any content loads. The Curated
  page stays hidden until a curated config parses into at least one row
  (`has-inputs` in `bz-content-provider.c`). Bazaar's YAML parser is strict:
  an unknown key rejects the whole file. Bazaar 0.9.x (Flathub 0.9.10) expects
  `rows:` of `section`/`banner`/`featured-carousel`/`articles`, so the
  pre-0.9 `css:` + `rows: [{sections: …}]` file in Bluefin
  `testing-44.20260917.5` shows no Curated tab (run 41193940707). Dakota and
  common main ship the new format.
- **Search.** A printable key typed into the window switches to the Search view,
  focuses the field and seeds it (`key_pressed` in `bz-window.c`). The field is
  a `text` node inside the Search panel, and results are `label`s with the app
  title. Type lower case: python-uinput's `_chars_to_events` maps only unshifted
  characters, so qecore's `Type text … with uinput` gets `None` for `F` and
  errors with no message.
- **Quit.** `<primary>q` is `app.quit`, which also calls the daemon's `Quit`.
  Send it as `Key combo: "<LEFTCTRL><Q>" with uinput`: qecore 4.19.3 turns each
  token into `KEY_<TOKEN>`, so `<Ctrl>` raises `KEY_CTRL … does not exist`.
  Alt+F4 only closes the window, and the daemon exits on its own after 5 s idle.
  Assert that no `Bazaar` frame is showing and that `flatpak ps` does not list
  the app. A `flatpak ps` error must fail the check, not read as "closed".
- **Coredumps.** The runner container has no `coredumpctl`, so the software
  suite checks the VM over SSH with `No coredump entries exist on the VM for`.
- **Keyboard focus.** uinput keys go to the active window. On fresh CI VMs the
  "Welcome to Bluefin" Shell modal (Skip / Take Tour) grabs the keyboard. AT-SPI
  tab clicks still worked behind it, but typing and Ctrl+Q went nowhere (run
  41196660163). Shell St buttons expose no AT-SPI actions, so `atspi_click` on
  Skip raises `available=[]` (run 41199678665). gnome-shell's `WelcomeDialog`
  binds Skip to `Clutter.KEY_Escape`, and the modal holds the grab. After
  qecore's `before_scenario` (which sets up `context.embed`), the software
  environment sends one uinput `ESC` and polls until the Skip button is gone. A
  modal that stays is a hook error. Every keyboard step first waits for the
  Bazaar frame's `active` state.
- **qecore "No scenario matched tags".** qecore's `after_all` asserts unless its
  own `before_scenario` cleared `sandbox._scenario_skipped`. The software
  environment calls that hook only for GUI scenarios, so it clears the flag
  itself once a scenario passes every skip gate. A run where every scenario
  skips still fails.


When scaffolding multiple feature areas at once:
- One agent per feature area, all in parallel
- Each agent needs: feature file path, steps file path, a reference feature to follow, dogtail API constraints, the duplicate-step check command
- After swarm completes, always validate:

```bash
python3 -m py_compile tests/<suite>/features/steps/*.py
grep -h "^@step" tests/<suite>/features/steps/*.py | sort | uniq -d
```
