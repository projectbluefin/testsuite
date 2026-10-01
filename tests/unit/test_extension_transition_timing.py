"""Controlled guest-observation timing; this does not validate live Clutter rendering."""

from types import SimpleNamespace
import time

import pytest

from tests.extensions.features.steps.shade_inactive_windows_steps import disable_during_transition


def _guest_with_fade(monkeypatch, *, disable_latency, removes_transition):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(time, "sleep", lambda delay: setattr(clock, "now", clock.now + delay))

    class Guest:
        disabled = False
        observations = 0

        def shell_json(self, expression):
            self.observations += 1
            if self.observations == 1:
                # The timeline is not yet available. This polling latency must
                # not reduce a later successfully observed fade's budget.
                clock.now += 1.0
                return None
            clock.now += 0.05
            if self.disabled:
                return {"effectPresent": not removes_transition, "transitionPresent": not removes_transition}
            return {
                "mapped": True, "focused": False,
                "effectPresent": True, "effectEnabled": True,
                "transitionPresent": True, "transitionPlaying": True,
                "transitionDuration": 1000, "transitionElapsed": 100,
            }

        def disable(self):
            clock.now += disable_latency
            self.disabled = True

    guest = Guest()
    context = SimpleNamespace(extension=guest, shade_windows={"Text Editor": {"sequence": 1}})
    return context, guest, clock




def test_an_immediately_observed_retained_transition_fails(monkeypatch):
    context, _, _ = _guest_with_fade(monkeypatch, disable_latency=0.2, removes_transition=False)
    with pytest.raises(AssertionError, match="remove the running effect and transition"):
        disable_during_transition(context, "Text Editor")


def test_natural_completion_cannot_pass_after_the_observation_budget_expires(monkeypatch):
    context, _, _ = _guest_with_fade(monkeypatch, disable_latency=1.0, removes_transition=True)
    with pytest.raises(AssertionError, match="safety margin"):
        disable_during_transition(context, "Text Editor")


def test_an_immediately_observed_removed_transition_passes(monkeypatch):
    context, _, _ = _guest_with_fade(monkeypatch, disable_latency=0.2, removes_transition=True)
    disable_during_transition(context, "Text Editor")
