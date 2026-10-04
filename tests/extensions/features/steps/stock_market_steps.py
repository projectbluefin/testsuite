"""Observe Stock Market's rendered actors through the guest-local Shell bridge."""

import json
import shutil
from pathlib import Path

from behave import given, step, then, when

from tests.shared.extension_session import installed_path
from tests.shared.guest_owned_processes import (
    assert_no_guest_owned_processes,
)


# Source: stock-market-binhnguyensoft.com at
# 667e40171ca6249b846e72cf28e314c5f3a79832 (extension.js and language.js).
# Only public actor APIs are used; extension controllers are not inspected.
_ACTOR_PROBE = """
    const walk = actor => [actor, ...actor.get_children().flatMap(walk)];
    const hasClass = (actor, name) =>
        (actor.get_style_class_name?.() ?? '').split(/\\s+/).includes(name);
    const find = (root, name) => walk(root).filter(actor => hasClass(actor, name));
    const rendered = actor => {
        const [width, height] = actor.get_transformed_size();
        return actor.is_mapped() && actor.is_visible() &&
            actor.get_paint_opacity() > 0 && width > 0 && height > 0;
    };
    const cards = find(global.stage, 'stocks-card');
"""


def _observe(result):
    return "(() => {" + _ACTOR_PROBE + "return " + result + ";})()"


def _symbols(table):
    assert table is not None and table.headings == ["symbol"], (
        "Stock Market symbols require a single 'symbol' table column"
    )
    return [row["symbol"] for row in table]


@given("Stock Market is disabled for configuration")
def stock_market_disabled_for_configuration(context):
    context.extension.disable()
    context.extension.wait_for(_observe("cards.length"), expected=0)


@given('the Stock Market language setting is "{language}"')
@when('the Stock Market language setting is "{language}"')
def stock_market_language(context, language):
    assert language in {"en", "vi"}, f"Unsupported explicit test language: {language!r}"
    context.extension.set_setting("language", json.dumps(language))


@given("the Stock Market watchlist contains these symbols:")
def stock_market_watchlist(context):
    context.extension.set_setting("symbols", json.dumps(_symbols(context.table)))


@given("the Stock Market watchlist is empty")
def stock_market_empty_watchlist(context):
    # An empty list takes the extension's real no-fetch branch, making the
    # translated timestamp and empty-state labels deterministic without fixtures.
    context.extension.set_setting("symbols", "[]")


@given("the Stock Market position settings are left {left:d} and top {top:d}")
@when("the Stock Market position settings are left {left:d} and top {top:d}")
def stock_market_position(context, left, top):
    context.extension.set_setting("left", str(left))
    context.extension.set_setting("top", str(top))


@then("exactly one Stock Market card is mapped on the desktop")
def stock_market_one_card(context):
    context.extension.wait_for(_observe("cards.map(rendered)"), expected=[True])


@then("no Stock Market card remains in the Shell actor tree")
def stock_market_no_card(context):
    # Count every matching actor, including hidden/unmapped remnants.
    context.extension.wait_for(_observe("cards.length"), expected=0)


@then("Stock Market displays these labels:")
def stock_market_labels(context):
    table = context.table
    assert table is not None and table.headings == ["style_class", "text"], (
        "Stock Market labels require 'style_class' and 'text' table columns"
    )
    expected = {}
    for row in table:
        expected.setdefault(row["style_class"], []).append(row["text"])
    assert expected, "Provide the expected rendered Stock Market labels"
    selectors = json.dumps(list(expected))
    result = f"""cards.map(card => Object.fromEntries(
        {selectors}.map(styleClass => [styleClass,
            find(card, styleClass).map(label =>
                rendered(label) ? label.get_text() : null)
        ])
    ))"""
    context.extension.wait_for(_observe(result), expected=[expected])


@then("Stock Market shows exactly {count:d} watchlist rows in this order:")
def stock_market_rows(context, count):
    symbols = _symbols(context.table)
    assert len(symbols) == count, "The explicit row count must match the expected symbol table"
    result = """cards.map(card => find(card, 'stocks-row').map(row =>
        rendered(row) ? find(row, 'stocks-symbol').map(label =>
            rendered(label) ? label.get_text() : null) : null
    ))"""
    # The helper returns the selected symbols even on a Yahoo outage. No price,
    # timestamp, cache warning, or live-success assertion depends on the network.
    # Allow its real bounded fetch/fallback cycle to complete before inspecting UI.
    context.extension.wait_for(
        _observe(result), expected=[[[symbol] for symbol in symbols]], timeout=30
    )


@then("the Stock Market card is left {left:d} and top {top:d} from the primary monitor origin")
def stock_market_position_observed(context, left, top):
    result = """cards.map(card => {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor || !rendered(card)) return null;
        const [x, y] = card.get_transformed_position();
        return [x - monitor.x, y - monitor.y];
    })"""
    context.extension.wait_for(_observe(result), expected=[[left, top]])


_STOCK_NONZERO_EXIT_STUB = """#!/usr/bin/env python3
# Test fixture: simulate a Python/helper nonzero-exit path. The real source
# hardcodes /usr/bin/curl, so a PATH stub cannot replace it; this replaces
# the helper itself with a stub that exits non-zero so the SafeCommandRunner
# surfaces the real "Tiến trình lấy giá thất bại" path.
import sys

sys.exit(1)
"""


def _restore_stock_helper(stub_path, backup_path):
    if backup_path is not None and Path(backup_path).exists():
        shutil.move(str(backup_path), str(stub_path))


def _stock_install_helper_stub(context):
    info = context.extension.command(["gnome-extensions", "info", context.extension.uuid]).stdout
    package_path = installed_path(info)
    helper = package_path / "stocks_fetch.py"
    if not helper.exists():
        raise AssertionError(f"Stock Market helper missing in installed package: {helper}")
    backup = helper.with_name(helper.name + ".test-backup")
    if backup.exists():
        raise AssertionError(f"Previous Stock Market helper backup leaked: {backup}")
    shutil.move(str(helper), str(backup))
    helper.write_text(_STOCK_NONZERO_EXIT_STUB, encoding="utf-8")
    helper.chmod(0o755)
    context.extension_cleanups.append((_restore_stock_helper, (helper, backup)))


@given("the Stock Market Python helper is replaced with a nonzero-exit stub")
def stock_helper_replaced_with_nonzero_stub(context):
    _stock_install_helper_stub(context)


@step("no Stock Market helper or curl child process remains for the candidate")
def stock_no_owned_processes(context):
    assert_no_guest_owned_processes(
        context, ("stocks_fetch.py", "/usr/bin/curl")
    )
