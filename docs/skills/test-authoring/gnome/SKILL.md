---
name: gnome
version: "1.0"
last_updated: "2026-07-29"
id: gnome
one_line_purpose: Write GNOME Shell, AT-SPI, and dogtail interaction tests.
entry_point: docs/skills/test-authoring/gnome/SKILL.md
category: test-authoring
mcp_compliance_level: partial
status: active
dependencies: []
tags: [gnome, atspi, dogtail]
description: "How to write GNOME Shell / AT-SPI / dogtail tests for the testsuite repo. Load when editing GNOME interaction steps."
metadata:
  type: pattern
  audience: agents
  maturity: stable
  context7-sources:
    - /GNOME/mutter
    - /GNOME/gnome-shell
    - /micheleg/dash-to-dock
---
# GNOME Desktop Testing Reference


## When to Use

- Writing or debugging GNOME Shell, AT-SPI, or dogtail interactions
- Implementing Shell.Eval-based steps (quick settings, overview, extensions)
- Adding extension-state checks for smoke or bazzite suites
- Debugging AT-SPI accessibility node failures in headless QEMU

## When NOT to Use

- SSH-based system checks → `docs/skills/test-authoring/behave/SKILL.md` shared SSH steps
- CI workflow or runner container setup → `docs/skills/ci-ops/ops/SKILL.md`
- Suite scaffolding or step hygiene → `docs/skills/test-authoring/behave/SKILL.md`

## Core Process


1. Identify whether the scenario needs AT-SPI interaction, Shell.Eval, or only subprocess/CLI checks.
2. Reuse existing smoke helpers first (`launch_background()`, `_run_host()`, `_eval_bool()`, `_wait_eval_bool()`).
3. Prefer desktop-file launch targets before direct commands for GUI apps so D-Bus activation and AT-SPI registration work in CI.
4. Poll for visible widgets or windows; avoid unconditional sleeps when a retry loop can prove readiness.
5. Validate locally with `python3 -m py_compile tests/<suite>/features/steps/*.py`, duplicate-step detection, `ruff`, and `behave --dry-run`.

`tests.shared.wait_for_shell.wait_for_shell()` is the GNOME Shell startup gate. Its contract is: retry Shell.Eval failures, retry when AT-SPI exposes no panel yet, retry on transient exceptions, retry when the session bus socket disappears during a GDM restart (re-resolving the bus address each attempt), require consecutive stable checks, then fail with a per-error-class breakdown once the wall-clock budget is exhausted.

## Stack


| Layer | Component | Install |
|---|---|---|
| BDD runner | behave | pip |
| Session bridge | qecore-headless | pip |
| GUI automation | dogtail (AT-SPI) | pip |
| Wayland coord bridge | gnome-ponytail-daemon | `sudo dnf install gnome-ponytail-daemon` inside VM |
| Shell bridge | `org.gnome.Shell.Eval` | built-in (requires `unsafe_mode=true`) |

## Screen Lock/Unlock D-Bus calls (GNOME 50)


In GNOME 50, `Main.screenShield.lock(true)` via `Shell.Eval` is deprecated and fails. Use the stable D-Bus interface `org.gnome.ScreenSaver.Lock` to lock the session, and `org.gnome.ScreenSaver.SetActive false` to unlock it:

```python
# Locking screen:
cmd = "source /tmp/session.env 2>/dev/null; gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver --method org.gnome.ScreenSaver.Lock"
_run_host(cmd)

# Unlocking screen:
cmd = "source /tmp/session.env 2>/dev/null; gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver --method org.gnome.ScreenSaver.SetActive false"
_run_host(cmd)
```

## Reading a static D-Bus property (ShellVersion canary)

To record the running GNOME Shell version for version-readiness tracking
(GNOME 51, issue #826), read the static `org.gnome.Shell` property
`ShellVersion` directly — it is **not** a Shell JS expression, so do not use
`Shell.Eval`. Route through SSH inside the runner container like the
`Shell.Eval` helpers:

```python
# ponytail: informational canary — never raise, only warn, so a pre-flip
# gnomeos-51 image reporting a new version still passes the suite.
from tests.shared.gnome_shell_steps import _IN_CONTAINER, _ssh_run

gdbus_get = [
    'gdbus', 'get', '--session',
    '--dest', 'org.gnome.Shell',
    '--object-path', '/org/gnome/Shell',
    '--interface', 'org.gnome.Shell',
    'ShellVersion',
]
version = ""
try:
    if _IN_CONTAINER:
        raw = _ssh_run("source /tmp/session.env 2>/dev/null; " + " ".join(gdbus_get), timeout=15)
        version = (raw or "").strip()
    else:
        out = subprocess.run(gdbus_get, capture_output=True, text=True, timeout=15)
        version = (out.stdout or "").strip()
        if out.returncode != 0:
            detail = (out.stderr or out.stdout or "").strip()
            print(f"WARNING: gdbus returned {out.returncode} reading ShellVersion: {detail}", flush=True)
except Exception as exc:
    print(f"WARNING: could not read ShellVersion: {exc}", flush=True)
    return

print(f"GNOME Shell ShellVersion: {version or '<unreadable>'}", flush=True)
```

Tag the scenario `@informational` so it runs and reports but never gates
promotion. See `tests/vanilla-gnome/features/steps/steps.py` for the landing
step and `gnome_core.feature` for the scenario.

## Remote session commands from the runner container

Commands that access the GNOME user session, including `gsettings`, `gdbus
--session`, and Mutter `DisplayConfig` helpers, must source the session
environment on the VM before running:

```bash
source /tmp/session.env 2>/dev/null; gsettings get org.gnome.mutter experimental-features
```

The SSH connection itself does not inherit `DBUS_SESSION_BUS_ADDRESS` or
`WAYLAND_DISPLAY`; without this prefix, remote session calls can target no bus
or the wrong user session and produce misleading test failures.

In container mode (or nested test runners), `environment.py` automatically writes
`/tmp/session.env` at session initialization with the active `DBUS_SESSION_BUS_ADDRESS`,
`XDG_RUNTIME_DIR`, `WAYLAND_DISPLAY`, and `XDG_SESSION_TYPE`. `_run_host()` ensures
the file is present and executes commands under bash so POSIX `/bin/sh` does not
abort on missing file errors.

## GNOME Shell extensions and AT-SPI health in smoke

Use the public `org.gnome.Shell.Extensions.GetExtensionInfo` D-Bus method to
assert an extension is enabled (`state` `1`). If the scenario promises visible
product behavior, enabled state is only the first diagnostic and must not
replace a rendering assertion. For Dash-to-Dock v106, recursively traverse the
public Clutter actor tree for its source-defined `dashtodockContainer` name and
require the actor to be mapped, visible, allocated, opaque, and slid open. Do
not inspect the extension's private `stateObj` or `dockManager` object graph.

When querying installed or enabled extensions in container mode, `gnome-extensions`
CLI may block if the desktop Settings portal times out; fall back to calling
`org.gnome.Shell.Extensions.ListExtensions` directly on `--dest org.gnome.Shell
--object-path /org/gnome/Shell` which evaluates in-process without portal dependencies.

Bluefin's welcome modal is not GNOME Initial Setup. Poll for its visible `Skip`
button through AT-SPI after the sandbox is ready and click it. Do not create a
system-wide `gnome-initial-setup-done` marker or kill GNOME first-run processes;
those do not target the Bluefin-specific dialog.

For AT-SPI health, ask `org.a11y.Bus.GetAddress` through the smoke suite's
`_run_host()` helper after sourcing `/tmp/session.env`. A bare subprocess (or
`pgrep`) can inspect the Fedora runner container rather than the VM GNOME
session and therefore does not prove the accessibility bus is usable.

## GNOME 50 Core Apps and Terminal (Ptyxis, Settings, Files)

In GNOME 50:
- **Ptyxis**: The terminal window title reflects the shell prompt (`user@host:~`), not just `"Terminal"` or `"Ptyxis"`. App assertions must match any visible frame belonging to the Ptyxis application.
- **Settings & Files**: Query `tree.root.applications()` first to resolve `"gnome-control-center"` and `"org.gnome.Nautilus"` immediately without triggering dogtail's 10-second per-name blocking retry loops. Prefer canonical desktop bus names (`"org.gnome.Nautilus"`) in lookup name tuples.

## GNOME 50 Firefox AT-SPI window resolution and chrome discovery

In GNOME 50, Firefox exposes its top-level window as `filler` or `frame` in AT-SPI, while web content and iframes within tabs also expose nested `frame` nodes (often containing child widgets such as `push button`). When tabs crash under containerized or headless environments, Firefox may also spawn `Tab crash reporter — Mozilla Firefox` frame nodes in the AT-SPI tree.

To resolve the genuine browser window reliably:
1. Query registered application name as `"Firefox"` first in `FIREFOX_APP_NAMES` to avoid a 10s retry timeout against `"firefox"`.
2. Filter out Mozilla crash reporter windows (`"crash reporter" in name.lower()`) so stale or crashed frames carrying a `page tab list` are not misidentified as browser windows.
3. Prioritize top-level candidates (`app.children`) before recursive searching, and require genuine browser chrome: `combo box`, `entry`, `autocomplete`, or `page tab list`. In GNOME 50, the Firefox address bar exposes role `combo box` (name `"Search with Google or enter address"`), and buttons use role `button`.
4. In headless Wayland container environments where `/dev/uinput` evdev keystrokes are not routed to windows by the compositor, provide an AT-SPI fallback via `atspi_click` targeting the `"Open a new tab (Ctrl+T)"` and tab `"Close tab"` buttons.
5. In headless Wayland environments, character entry via uinput maps punctuation and shifted keys (e.g. ':', uppercase) through an evdev lookup to avoid NoneType unpack errors. For Firefox URL navigation, remote IPC navigation provides a fallback when headless compositors drop input keystrokes, and address assertions accept both domain prefixes and loaded document titles. Clean shutdown falls back to process termination if uinput `<Ctrl><Q>` is unrouted.

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

## Screenshot on failure


Hook in `after_scenario`, before sandbox cleanup:

```python
from tests.shared.screenshot import take_screenshot

def after_scenario(context, scenario):
    if scenario.status == "failed":
        take_screenshot("failed", context)
```

`take_screenshot()` calls the native `org.gnome.Shell.Screenshot` D-Bus API.
Do not call `context.sandbox.shell.eval_js(...)` for screenshots — in qecore
4.16 `sandbox.shell` is an accessibility object and has no `eval_js` method.

## GNOME Extensions CLI (subprocess)


Smoke-suite extension steps run inside the VM via `subprocess`, not AT-SPI:

```python
import subprocess

# List installed extensions
result = subprocess.run(["gnome-extensions", "list"], capture_output=True, text=True)
extensions = [e.strip() for e in result.stdout.splitlines() if e.strip()]

# List enabled extensions
result = subprocess.run(["gnome-extensions", "list", "--enabled"], capture_output=True, text=True)
enabled = [e.strip() for e in result.stdout.splitlines() if e.strip()]
```

Note: `gnome-extensions` requires the GNOME session to be running. These steps run inside the qecore VM (local subprocess), not over SSH.

## Extension state via D-Bus (bazzite / GNOME 50)


For suites that need to poll an extension's activation state (e.g. the bazzite suite which runs over SSH), **do not** use `Shell.Eval + Main.extensionManager.lookup(uuid)?.state`. On GNOME 50 this API consistently returns state=6 (INITIALIZED) regardless of actual activation.

Use `org.gnome.Shell.Extensions.GetExtensionInfo` instead:

```python
import subprocess, re

def _extension_state(uuid: str) -> str:
    """Return extension state as a string integer. 99 = unknown / uninstalled."""
    result = subprocess.run(
        ['gdbus', 'call', '--session',
         '--dest', 'org.gnome.Shell',
         '--object-path', '/org/gnome/Shell/Extensions',
         '--method', 'org.gnome.Shell.Extensions.GetExtensionInfo',
         f"'{uuid}'"],            # ← single-quotes required; see GVariant note below
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return "99"
    m = re.search(r"'state':\s*<uint32\s+(\d+)>", result.stdout)
    return m.group(1) if m else "99"
```

**GVariant quoting (critical):** Extension UUIDs contain `@` and `.` which are invalid in a bare GVariant token. Always wrap the UUID in single quotes inside the Python string: `f"'{uuid}'"` → produces `'logomenu@aryan_k'` on the command line.

**State values:** 1=ENABLED, 2=DISABLED, 3=ERROR, 4=OUT_OF_DATE, 5=DOWNLOADING, 6=INITIALIZED (transient), 7=DISABLING (transient), 8=ENABLING (transient), 99=UNINSTALLED.

Poll through 6 and 8 with a deadline (Bazzite: use 90s — 11 extensions need time post-boot).

## Extension state in smoke suite (local subprocess / SSH bridge)


The smoke suite's UUID-specific extension checks use the same
`GetExtensionInfo` D-Bus call as bazzite, but route through the suite-local
`_run_host(...)` helper so they work both inside the VM and from the Fedora
runner container over SSH.

Bluefin's 9 bundled extensions each get a named scenario in
`tests/smoke/features/bluefin_extensions.feature`. Tag the
`search-light@icedman.github.com` scenario with `@bluefin` so dakota smoke runs
skip it via `environment.py`.

Use the distinct step phrase `GNOME extension "{uuid}" is enabled` (not
bazzite's `Extension "{uuid}" is enabled`) to avoid cross-suite step collisions.

## Bazaar on Bluefin: wait out the Refreshing spinner


Bluefin ships **Bazaar** (`io.github.kolunmi.Bazaar`), not GNOME Software's old
Explore/Installed toggle-button layout. For Bazaar UI tests:

- wait for a visible window named **`Bazaar`**
- then poll until any visible tab named **`Curated`**, **`Explore`**,
  **`Library`**, or **`Search`** appears
- accept both `page tab` and `toggle button` roles for those tabs

The first launch often shows a **Refreshing** spinner page before the
`AdwViewStack` content is ready. On GNOME 50, AT-SPI cache drops can also make
nodes disappear mid-query, so wrap Bazaar window/tab lookups in retry loops
with short sleeps and re-query the tree each attempt.

## Desktop notifications via gdbus (smoke suite)


Send a test notification from inside the VM:

```bash
gdbus call --session \
  --dest org.freedesktop.Notifications \
  --object-path /org/freedesktop/Notifications \
  --method org.freedesktop.Notifications.Notify \
  '' 0 '' 'Title' 'Body' '[]' '{}' 3000
# Returns: (uint32 N,)  — N is the notification ID (>0 on success)
```

Parse the ID from `context.notify_output` with `re.search(r'\(uint32 (\d+),\)', output)`. An ID of `0` means failure.

## Smoke desktop-identity checks: use `_run_host` + session env


For smoke steps that need session-scoped shell state (`XDG_SESSION_TYPE`,
`DISPLAY`, `WAYLAND_DISPLAY`) or VM-installed tools like `glxinfo`, prefer the
suite-local `_run_host(...)` helper over plain `subprocess.run(...)`.

Why: local smoke scenarios execute inside the VM during ad-hoc runs, but CI can
run them from the Fedora runner container. `_run_host(...)` transparently hops
to the VM over SSH in that case, and `source /tmp/session.env 2>/dev/null; ...`
preserves the GNOME user-session environment before probing Wayland or renderer
state.


## Per-app accessibility launch environment


Session-wide `gsettings set org.gnome.desktop.interface toolkit-accessibility true`
(set by `e2e.yml`) only enables the **GTK** atk-bridge. Applications that render
their own chrome build their AT-SPI tree from their own environment and must be
launched with explicit accessibility variables:

```python
FIREFOX_A11Y_ENV = {
    "GNOME_ACCESSIBILITY": "1",
    "ACCESSIBILITY_ENABLED": "1",
    "GTK_A11Y": "atk-bridge",
}
context.firefox_launch_target = launch_background(FIREFOX_LAUNCH_TARGETS, env=FIREFOX_A11Y_ENV)
```

`launch_background(targets, env=...)` in `tests/smoke/features/steps/app_support.py`
applies `env` on every launch path: exported before the command in SSH mode,
merged into `os.environ` for local `Popen`, and forwarded across the Flatpak
sandbox boundary with `--env=`. Environment set outside a Flatpak sandbox is
**not** visible inside it — always use the `env=` parameter, never a shell prefix.

An **exported Flatpak desktop entry is a trap**: an app ID under
`/var/lib/flatpak/exports/share/applications/` looks like an ordinary desktop
target, but `gio launch` / `gtk-launch` starts it inside the sandbox and silently
drops the launch environment. `launch_background()` detects the export path and
reroutes it through `flatpak run --env=`. Keep an explicit
`("flatpak", app_id)` target before the exported desktop entry when both are
listed, so the intended launch path is clear at the call site.

Symptom when this is missing: the application appears in the AT-SPI tree but its
window node has **no descendants** — no `entry`, `tool bar`, or `page tab list`.
Steps then fail late with confusing messages such as "address bar not found".

## Window-role checks must prove the subtree is populated


Since GNOME 50 some apps expose their toplevel as `filler` rather than `frame`,
so smoke helpers accept `{"frame", "filler"}`. Accepting a bare `filler` node on
its own is a **false pass**: it is exactly what an app exposes when its
accessibility engine never started. Require evidence of a real subtree:

```python
def _has_populated_a11y_tree(node) -> bool:
    return bool(node.findChildren(lambda n: n.roleName in CHROME_ROLES))
```

Prefer a `frame` with a populated subtree, fall back to a populated `filler`, and
otherwise fail with a message that names the likely cause
(`GNOME_ACCESSIBILITY` / `toolkit-accessibility`). Keep a
`require_a11y_tree=False` escape hatch for pure liveness checks such as
"the app is no longer running".

## Sleep discipline in step definitions


Unconditional `sleep(N)` calls inflate suite time — avoid them. Rules:

1. **`launch_background()` from qecore** — do NOT add `sleep(1)` after calling qecore's built-in `launch_background()`. The immediately-following "window is accessible" step has its own AT-SPI polling loop; the launch sleep is redundant there.

   **EXCEPTION — `_launch_app()` custom launcher**: The suite-local `_launch_app()` in `gnome_apps_steps.py` uses D-Bus app activation (`gio open` or `gtk-launch`), which is **asynchronous**. `sleep(1)` after a successful `_launch_app()` return is **required** as a D-Bus activation settle time — without it, `_wait_for_window()` starts polling before the process has registered with the AT-SPI accessibility bus, exhausts all retries (~10s), and fails on slower images (e.g. Dakota testing). Do not remove this sleep. The regression in PR #465 was caused by removing it.

2. **Polling loop intervals** — use 0.2s intervals in retry loops (`for _ in range(N): sleep(0.2)`). 0.5s is the old default; the loops already exit-early on success so tighter intervals help.

3. **GNOME Shell open/close animations** — use 0.2s after `_shell_eval()` open/close commands before checking state. The `_wait_eval_bool()` helper handles the real confirmation wait.

4. **Screenshot fastfetch** — terminal keep-open is `fastfetch; sleep 3` (not 10). Pre-screenshot delay `time.sleep(2)` (not 4). Both are already on QEMU where timing is slow.

5. **Never remove** — small sleeps after user-visible actions (sidebar clicks, key combos, focus transitions) that have no async poll to catch up: `sleep(0.2)` is the minimum. Do not go below 0.1s.

The pattern `for _ in range(N): ... sleep(X)` that returns early already IS exit-early. The gains come from removing the PRECEDING unconditional sleep, not from changing the loop.

## Red Flags


- Using `'true' in out` to check a Shell.Eval result (success_bool is always true)
- Calling `Shell.Eval` without first setting `global.context.unsafe_mode = true`
- Using `requireResult=False` with `findChild` (removed in dogtail 4.16)
- Importing `tests.shared.ssh_steps` into the smoke suite
- Using AT-SPI coordinate clicks on the top-bar (unreliable on GNOME 50+)
- Polling `Main.extensionManager.lookup(uuid)?.state` via Shell.Eval (returns 6 on GNOME 50)
- Using the SSH-based `_extension_state()` pattern in the smoke suite (smoke uses local subprocess)
- `_<app>_app()` helper does a single-pass lookup with no retry loop — will flake on GNOME 50 QEMU
- A `_<app>_window()` helper accepts `roleName "filler"` without checking that the node has descendants (false pass)
- A GUI app that renders its own chrome is launched without `GNOME_ACCESSIBILITY=1`
- A Flatpak-exported `.desktop` entry is launched with `gio launch`/`gtk-launch`
  while carrying an `env=` payload (the env never reaches the sandbox)
- A session-readiness loop caches the D-Bus session address or treats a missing bus socket as fatal (breaks across the qecore-headless GDM restart)

## Verification


- [ ] Shell.Eval results extracted with `_eval_bool()` / regex on second tuple element, never `'true' in out`
- [ ] `unsafe_mode=true` set before any Shell.Eval that reads protected state
- [ ] Extension state checked via `org.gnome.Shell.Extensions.GetExtensionInfo`, not `Shell.Eval`
- [ ] UUID wrapped in single quotes for GVariant: `f"'{uuid}'"` not `uuid`
- [ ] Smoke suite steps use `subprocess.run`, not SSH helpers
- [ ] `behave --dry-run tests/smoke/features/` passes before pushing
- [ ] Window-role helpers that accept `filler` also assert the node has a populated subtree
- [ ] Launch targets for Flatpak-packaged apps resolve to `flatpak run --env=`, not an exported desktop entry

## Common Rationalizations


- "A direct command launch is simpler." → For GUI apps, desktop-file activation is usually more reliable for AT-SPI registration.
- "I'll just sleep after launch." → Poll for the visible window instead; fixed sleeps bloat the suite and still flake.
- "This title match is good enough." → Prefer app-level AT-SPI lookup first, then use title fallback only when the app name is unstable.

## Red Flags


- New smoke app steps hardcode `/usr/share/applications/...` for Flatpak-only apps
- Step code uses `findChild(..., requireResult=...)`
- New GNOME steps duplicate existing step phrases in the suite
- New launch steps add unconditional post-launch sleeps instead of relying on accessibility polling

## Verification


- [ ] Reused existing GNOME/smoke helpers before adding new ones
- [ ] Launch targets prefer desktop files, with Flatpak or command fallback only when needed
- [ ] AT-SPI polling or Shell.Eval assertions replace fixed waits where possible
- [ ] `python3 -m py_compile tests/<suite>/features/steps/*.py` passes
- [ ] `grep -h "^@step" tests/<suite>/features/steps/*.py | sort | uniq -d` returns no duplicates
- [ ] `ruff check tests/ --select E,F,W --ignore E501` passes
- [ ] `behave --dry-run tests/<suite>/features/` passes for the touched suite

## On-demand references

Load these when you hit the specific topic:

- [dogtail and AT-SPI lookup patterns and retry discipline.](references/atspi.md)
- [Top-bar interactions and Shell.Eval parsing on GNOME 50+.](references/top-bar.md)
- [MIME, display, and session configuration in containerized tests.](references/display-config.md)
- [Deep dive: Preinstalled Flatpak desktop app launch checks](references/preinstalled-flatpak-desktop-app-launch-checks.md)
- [Session readiness across a GDM restart in containerized tests.](references/session-readiness.md)
- [Unit-testing smoke step modules with stubbed dependencies.](references/unit-testing-smoke-steps.md)
