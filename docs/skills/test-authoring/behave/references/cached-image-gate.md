---
name: cached-image-gate
description: "Gating scenarios on a pre-pulled OCI image with @requires_cached_image, and the masking trap that makes the tag inert."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Cached Image Gate

## Why the tag exists

A scenario that needs a container image on the device under test must never pull
that image itself. `distrobox create --image registry.fedoraproject.org/fedora-toolbox:latest`
against a cold podman store pulls hundreds of megabytes inside the scenario and
eats the CI timeout, so the run reports "distrobox is broken" when the real
finding is "the runner had no image". That is the blocker recorded on
`projectbluefin/testsuite#501` and tracked lab-side as `projectbluefin/lab#621`.

`@requires_cached_image` turns that blocker into a runtime condition instead of a
hand-maintained `@pending` marker.

## How it works

`tests/shared/image_cache.py` exposes `skip_when_image_not_cached(context, scenario)`.
A suite calls it from `before_scenario`, immediately after `skip_quarantine`:

```python
from tests.shared.image_cache import skip_when_image_not_cached

if skip_when_image_not_cached(context, scenario):
    return
```

For a tagged scenario it:

1. reads the image references out of the **scenario's own step text** — the
   feature file stays the single source of truth for what is under test, so the
   probe can never drift from the image the steps actually use;
2. runs `podman image exists <ref>` on the DUT for each distinct reference;
3. skips with the missing references named when any is absent.

`podman image exists` is local-only and never contacts a registry. That is
deliberate and load-bearing: a probe that could pull would trigger the very
timeout the gate exists to prevent. `tests/unit/test_image_cache.py` asserts the
probe command shape for exactly this reason.

An unreachable DUT counts as "not cached" — a failed SSH probe is not evidence
that an image is present, and skipping is the safe reading.

## Why the probe does not use `run_ssh`

`tests/shared/ssh_steps.py` looks like the obvious way to run the probe, but
importing it registers its `@step` phrases into behave's global registry. Two of
them — `SSH command return code is "{code}"` and `Last command output contains
"{text}"` — are also defined by `tests/dx/features/steps/steps.py`. A DX
`before_scenario` that imported the module would raise `AmbiguousStep` and take
the entire suite down, and the DX suite is the first consumer of this gate.

So the probe resolves connection details from `tests/shared/ssh_config.py` — the
helper explicitly documented for "suite `environment.py` hooks that probe the VM
directly", carrying no step definitions — and shells out itself.
`test_gate_does_not_import_the_shared_ssh_step_library` pins this.

The probe also leaves `context.command_stdout` / `context.ssh_rc` alone, unlike
a step. It runs before `before_scenario` resets per-scenario state, so writing
to those would leak a probe result into the scenario's first assertion.

## Three rules that are easy to get wrong

**It is not a non-runnable tag.** Do not add it to `_SKIP_TAGS` in
`tests/shared/quarantine.py`, to `NON_RUNNABLE_TAGS` in
`tests/shared/behave_retry.py`, or to `BEHAVE_TAG_ARGS` in `e2e.yml`. It is a
runtime capability gate in the family of `@requires_brew` and
`@requires_toggle_action`: the scenario must begin running the moment the image
is cached, with no feature-file edit and no follow-up PR.

**Never pair it with `@pending`, `@future`, `@quarantine`, or `@hardware_blocked`.**
`skip_quarantine` runs first and returns early, so the gate never executes and the
tag is inert — the masking trap documented in
`docs/skills/test-authoring/suite-map/SKILL.md`. This is not hypothetical: the
three distrobox scenarios carried `@pending @requires_cached_image` from the day
they landed, and the tag did nothing at all until #501 was finished.
`test_tagged_scenarios_are_not_masked_by_a_non_runnable_tag` fails the build if it
recurs.

**Name the image with a registry and a tag.** `registry.fedoraproject.org/fedora-toolbox:latest`
is recognised; bare `fedora:latest` is not, because what it resolves to depends on
the DUT's `registries.conf` search list — the probe could then disagree with the
pull the scenario would perform. A tagged scenario whose steps name no qualified
image is an authoring error, and
`test_every_tagged_scenario_names_an_image` fails on it rather than letting it
skip forever while looking like an infra gap.

## Verifying a gated scenario

`behave --dry-run` cannot exercise the gate: it never calls `before_scenario`.
Check the gate with the unit tests, and check the scenario body against a DUT
that has the image pre-pulled:

```bash
python3 -m pytest tests/unit/test_image_cache.py -q
podman pull registry.fedoraproject.org/fedora-toolbox:latest   # on the DUT
```
