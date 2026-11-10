"""Shared helpers for non-runnable scenario tags.

Covers @quarantine, @future, @pending and @hardware_blocked.
"""

from __future__ import annotations


_SKIP_REASONS = {
    "quarantine": "@quarantine — known flaky, skipping",
    "pending": "@pending — placeholder coverage, skipping",
    "future": "@future — planned coverage not yet runnable, skipping",
    "hardware_blocked": "@hardware_blocked — required hardware unavailable, skipping",
}

# Order matters only for the reported reason when several tags coexist.
# Precedence documented in docs/skills/test-authoring/suite-map/SKILL.md:
# @quarantine > @hardware_blocked > @future > @pending > active.
_SKIP_TAGS = ("quarantine", "hardware_blocked", "future", "pending")


def is_non_runnable(scenario) -> bool:
    """True when a skip tag parks the scenario, so it never runs."""
    scenario_tags = set(getattr(scenario, "effective_tags", getattr(scenario, "tags", ())))
    return any(tag in scenario_tags for tag in _SKIP_TAGS)


def skip_quarantine(scenario) -> bool:
    scenario_tags = set(getattr(scenario, "effective_tags", scenario.tags))
    for tag in _SKIP_TAGS:
        if tag not in scenario_tags:
            continue
        try:
            scenario.skip(_SKIP_REASONS[tag])
        except TypeError:
            scenario.skip()
        return True
    return False
