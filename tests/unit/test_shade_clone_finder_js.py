"""Regression for the Shade clone-finder JS expression in shade steps.

Issue #919 originally matched overview clones by ``actor.get_meta_window?.()
?.get_stable_sequence() === sequence``. WindowPreview (the parent of the
clone actor) exposes ``metaWindow`` as a JS property, not a getter method;
Clutter.Clone itself has no ``get_meta_window`` accessor at all, so the
walk over ``Main.layoutManager.overviewGroup`` never matched a real clone
and the assertion pinned the wrong model. The fix keys on
``Clutter.Clone.source === original`` instead.

These tests pin the new expression:

* it reaches the original actor via ``get_meta_window`` (the original is a
  MetaWindowActor; only that has the getter);
* the clone walk on overviewGroup keys on ``actor.source === original``;
* a non-clone child of overviewGroup that happens to share the original's
  MetaWindow sequence is *not* picked up;
* the clones-removed walker resolves the originals once at the top, then
  walks overviewGroup for ``actor.source`` matches. Re-deriving originals
  inside the recursive walk would O(n^2) the traversal.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.extensions.features.steps import shade_inactive_windows_steps


def _context(sequence=1, shade_windows=None):
    return SimpleNamespace(
        shade_windows=shade_windows or {"Text Editor": {"sequence": sequence}},
    )


def test_clone_state_expression_keys_on_source_not_get_meta_window():
    """The clone match clause must be ``actor.source === original``, not a
    ``get_meta_window`` walk. Pinning it as a substring prevents the
    regression that briefly slipped through review: the walk returned no
    matches because WindowPreview exposes metaWindow as a property.
    """
    expression = shade_inactive_windows_steps._clone_state(_context(sequence=42), "Text Editor")
    assert "actor.source === original" in expression, (
        "clone match must key on Clutter.Clone.source; "
        "WindowPreview has no get_meta_window() accessor"
    )
    assert "actor.get_meta_window?.()" not in expression, (
        "the clone walk must not call get_meta_window on overviewGroup children; "
        "Clutter.Clone has no such accessor and WindowPreview exposes metaWindow "
        "as a JS property"
    )


def test_clone_state_expression_resolves_original_via_get_meta_window():
    """The *original* actor is still resolved with ``get_meta_window()`` --
    MetaWindowActor is the only one that has the getter. The walk that
    follows must not.
    """
    expression = shade_inactive_windows_steps._clone_state(_context(sequence=42), "Text Editor")
    assert "actor.get_meta_window()?.get_stable_sequence() === sequence" in expression, (
        "the original-actor lookup still uses MetaWindowActor.get_meta_window(); "
        "only the overviewGroup clone walk drops it"
    )


def test_clone_state_expression_skips_the_original_itself():
    """A clone cannot be the original. The walker records the actor only
    when ``actor !== original``; pinning the guard prevents a future
    refactor from accidentally counting the original window as its own
    clone (which would always pass the assertion vacuously).
    """
    expression = shade_inactive_windows_steps._clone_state(_context(sequence=42), "Text Editor")
    assert "actor !== original && actor.source === original" in expression


def test_clones_removed_walker_keys_on_source_not_get_meta_window():
    """The clones-removed walker asserts the *absence* of leftover clones;
    it must use the same source-keyed match. Otherwise a leftover clone
    (whose actor has no get_meta_window accessor) would be invisible and
    the assertion would always pass.
    """
    # The walker's JS is interpolated inside wait_for at the call site;
    # recover it from the wait_for argument by re-running the helper and
    # reading the source.
    captured = {}

    def fake_wait_for(expression, *args, **kwargs):
        captured["expression"] = expression
        raise AssertionError("stop -- we only care about the captured expression")

    guest = SimpleNamespace(wait_for=fake_wait_for)
    context = SimpleNamespace(
        shade_windows={
            "Text Editor": {"sequence": 1},
            "Calculator": {"sequence": 2},
        },
        shade_focused_application="Text Editor",
        extension=guest,
    )
    with pytest.raises(AssertionError, match="stop -- we only care about the captured expression"):
        shade_inactive_windows_steps.assert_overview_clones_removed(context, "Text Editor", "Calculator")

    expr = captured["expression"]
    assert "actor.source === original" in expr, (
        "leftover-clone match must key on Clutter.Clone.source; "
        "Clutter.Clone has no get_meta_window accessor"
    )
    # The get_meta_window lookup is fine on the originals resolver (the
    # originals are MetaWindowActors, the only actors that have the
    # getter). The recursive walk over overviewGroup must not use it --
    # that is where the vacuous-pass regression lived.
    find_clones_open = expr.index("const findClones = actor =>")
    recursion_close = expr.index("})()", find_clones_open)
    recursion_body = expr[find_clones_open:recursion_close]
    assert "actor.get_meta_window?.()" not in recursion_body, (
        "the leftover-clone walk must not use get_meta_window on overviewGroup "
        "children -- the leftover clone is invisible to that lookup"
    )


def test_clones_removed_walker_resolves_originals_outside_the_recursion():
    """Resolving originals once at the top of the expression (a single
    filter on get_window_actors) keeps the recursive walk O(n) instead of
    O(n^2). The walker's expression must read the originals outside the
    ``findClones`` recursion.
    """
    captured = {}

    def fake_wait_for(expression, *args, **kwargs):
        captured["expression"] = expression
        raise AssertionError("stop -- we only care about the captured expression")

    guest = SimpleNamespace(wait_for=fake_wait_for)
    context = SimpleNamespace(
        shade_windows={
            "Text Editor": {"sequence": 1},
            "Calculator": {"sequence": 2},
        },
        shade_focused_application="Text Editor",
        extension=guest,
    )
    with pytest.raises(AssertionError, match="stop -- we only care about the captured expression"):
        shade_inactive_windows_steps.assert_overview_clones_removed(context, "Text Editor", "Calculator")

    expr = captured["expression"]
    # original resolver happens before the recursion starts
    original_idx = expr.index("global.get_window_actors().filter")
    recursion_idx = expr.index("findClones(Main.layoutManager.overviewGroup)")
    assert original_idx < recursion_idx, (
        "resolve the originals once before recursing; "
        "filtering inside the recursion is O(n^2) and the assertion's "
        "timing budget does not cover it"
    )
