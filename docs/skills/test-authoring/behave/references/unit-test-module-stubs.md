---
name: unit-test-module-stubs
description: "Stubbing tests.shared submodules in unit tests without breaking lazy imports."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Unit Test Module Stubs

Unit tests under `tests/unit/` import suite `steps.py` and `environment.py`
modules directly, outside a behave run. Those modules star-import
`tests.shared.*`, so the tests inject stubs into `sys.modules` first.

## Stub the package, not just the submodule

A suite module that does `from tests.shared.ssh_steps import *` at import time
is satisfied by a submodule stub alone. But `environment.py` also imports some
helpers **lazily, inside a hook**:

```python
def before_scenario(context, scenario):
    from tests.shared.quarantine import skip_quarantine
```

That lazy import runs when the hook is *called*, not when the module is
imported — and by then Python re-resolves `tests.shared` as a package. If the
test replaced `tests.shared` with a bare module object:

```python
# Wrong: no __path__, so submodule resolution fails later
sys.modules["tests.shared"] = types.ModuleType("tests.shared")
```

the hook raises `ModuleNotFoundError: 'tests.shared' is not a package`.

A bare `types.ModuleType` has no `__path__` attribute, and `__path__` is exactly
what marks a module as a package for submodule resolution.

## The failure only appears in isolation

This bug hides in a full-suite run. Another test file that imported the genuine
`tests.shared` package leaves it cached in `sys.modules`, so a later file's bad
stub is never consulted. The suite passes; the single file fails:

```bash
# Passes — earlier files cached the real package
python3 -m pytest tests/unit/ -q

# Fails — nothing seeded the cache first
python3 -m pytest tests/unit/test_common_steps.py -q
```

**Always run a new or modified unit test file on its own** before opening a PR.
A green full-suite run does not prove the file is self-contained.

## Correct pattern

Drop any non-package stub, then import the real package so `__path__` is set:

```python
def _ensure_tests_shared_package() -> None:
    mod = sys.modules.get("tests.shared")
    if mod is not None and not hasattr(mod, "__path__"):
        del sys.modules["tests.shared"]
    import tests.shared  # noqa: F401,PLC0415  — real package, has __path__
```

Call it before installing submodule stubs. Stub the *submodules*
(`tests.shared.ssh_steps`, `tests.shared.quarantine`, `tests.shared.timing`)
and leave the parent package genuine.

## Stubbing a step module that imports from `steps.steps`

Some step modules do `from steps.steps import _run_host`, a path that only
resolves during a behave run because behave puts the suite's `steps/` directory
on `sys.path`. Register a package stub with an explicit empty `__path__` before
importing the module under test:

```python
steps_pkg = types.ModuleType("steps")
steps_pkg.__path__ = []  # marks it a package so `steps.steps` can resolve
sys.modules["steps"] = steps_pkg
sys.modules["steps.steps"] = steps_steps_stub
```


## Testing steps that make multiple sequential SSH calls

Steps that call `_ssh()` more than once need a helper that serves canned
`subprocess.run` results **in order**.  The existing `_FakeSSH` context
manager in `tests/unit/test_dx_steps.py` is the canonical pattern:

```python
def _make_ssh_proc(stdout="", rc=0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = rc
    return proc


class _FakeSSH:
    """Patches subprocess.run and serves canned results per call, in order."""

    def __init__(self, module, results):
        self.module = module
        self.results = list(results)
        self.calls = []       # captures raw args list for each call
        import unittest.mock as um
        self._patcher = um.patch("subprocess.run", side_effect=self._run)

    def _run(self, args, **kwargs):
        self.calls.append(args)
        if not self.results:
            raise AssertionError("unexpected extra SSH call")
        return self.results.pop(0)

    def __enter__(self):
        self._patcher.start()
        return self

    def __exit__(self, *exc):
        self._patcher.stop()
```

```python
def test_happy_path(self):
    m = _import_dx_steps()
    ctx = _ssh_ctx()
    with _FakeSSH(m, [
        _make_ssh_proc("", 0),                   # call 1 — cleanup
        _make_ssh_proc("", 0),                   # call 2 — create
        _make_ssh_proc("test-box  image:latest", 0),  # call 3 — list
    ]):
        m.dx_distrobox_can_be_created(ctx, "test-box", "image:latest")

def test_command_flags(self):
    m = _import_dx_steps()
    ctx = _ssh_ctx()
    with _FakeSSH(m, [...]) as ssh:
        m.dx_distrobox_can_be_created(ctx, "test-box", "image:latest")
    create_cmd = ssh.calls[1][-1]    # second call, last element is the command string
    assert "--yes" in create_cmd
```

Key behaviours to test for any multi-SSH step:
- **Happy path** — all calls succeed, no exception raised
- **Each SSH call failing** — verify the right `AssertionError` message
- **Conditional acceptance** — e.g., cleanup rc=1 or "No such container" text is OK
- **Command shape** — verify required flags appear in the right call via `ssh.calls[N][-1]`

## Verification

- [ ] The new test file passes **run on its own**, not only in a full-suite run
- [ ] No `sys.modules["tests.shared"]` assignment to a bare `types.ModuleType`
- [ ] Any package stub that needs submodules sets `__path__`
- [ ] Stubs are installed before the module under test is imported, and stale
      entries for that module are deleted from `sys.modules` first
