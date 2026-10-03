"""Observe SJC Gold through the rendered Shell actor tree and real settings.

Actor classes and the unstyled parent widget's monitor-relative origin follow
extension.js at 1588c7683d113e42d2f36a69165a9bacd6b1d95b. Quote fetching is
not mocked here; successful HTTPS responses belong to the fixture lane (#909).
"""

import json
import shutil
from pathlib import Path

from behave import given, step, then, when

from tests.shared.extension_session import installed_path
from tests.shared.guest_owned_processes import (
    assert_no_guest_owned_processes,
)


_SJC_ACTORS = """
    const hasClass = (actor, name) =>
        (actor.get_style_class_name?.() ?? '').split(/\\s+/).includes(name);
    const descendants = root => {
        const result = [];
        const visit = actor => {
            result.push(actor);
            for (const child of actor.get_children())
                visit(child);
        };
        if (root)
            visit(root);
        return result;
    };
    const rendered = actor => {
        if (!actor || !actor.is_visible() || !actor.is_mapped() ||
            !actor.has_allocation() || actor.get_paint_opacity() === 0)
            return false;
        const [width, height] = actor.get_transformed_size();
        return width > 0 && height > 0;
    };
    // Count every card, including invisible leftovers, before checking mapping.
    const cards = descendants(global.stage).filter(a => hasClass(a, 'sjc-card'));
    const card = cards.length === 1 ? cards[0] : null;
    // The source adds sjc-card to an unstyled St.Widget whose allocation sets
    // the primary-monitor origin. Card padding is not the preference offset.
    const widget = card?.get_parent();
    const cardRendered = rendered(card) && rendered(widget);
"""


def _sjc_expression(body):
    return "(() => {" + _SJC_ACTORS + body + "})()"


def _wait_for_sjc(context, body):
    context.extension.wait_for(_sjc_expression(body))


@when('I set the SJC Gold "{key}" preference to {value:d}')
def set_sjc_position_preference(context, key, value):
    assert key in {"left", "top"}, f"Not an SJC Gold position preference: {key}"
    context.extension.set_setting(key, str(value))


@then("exactly one SJC Gold desktop card is mapped and allocated")
def sjc_card_is_rendered(context):
    _wait_for_sjc(context, "return cardRendered;")


@then('the SJC Gold header reads "{text}"')
def sjc_header_is_rendered(context, text):
    expected = json.dumps(text, ensure_ascii=False)
    _wait_for_sjc(
        context,
        """
        if (!cardRendered)
            return false;
        const headers = descendants(card).filter(a => hasClass(a, 'sjc-header'));
        if (headers.length !== 1 || !rendered(headers[0]))
            return false;
        const titles = descendants(headers[0]).filter(a => hasClass(a, 'sjc-title'));
        return titles.length === 1 && rendered(titles[0]) &&
            titles[0].text === """ + expected + ";",
    )


@then("the SJC Gold price labels are rendered:")
def sjc_price_labels_are_rendered(context):
    expected = json.dumps([row["text"] for row in context.table], ensure_ascii=False)
    _wait_for_sjc(
        context,
        """
        if (!cardRendered)
            return false;
        const priceRows = descendants(card).filter(a => hasClass(a, 'sjc-price-row'));
        if (priceRows.length !== 1 || !rendered(priceRows[0]))
            return false;
        const labels = descendants(priceRows[0]).filter(a => hasClass(a, 'sjc-label'));
        const expected = """ + expected + """;
        return labels.length === expected.length && labels.every(rendered) &&
            expected.every(text => labels.filter(label => label.text === text).length === 1);
        """,
    )


@then(
    "the SJC Gold card is rendered at left {left:d} and top {top:d} "
    "on the primary monitor"
)
def sjc_card_has_monitor_position(context, left, top):
    _wait_for_sjc(
        context,
        """
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor || !cardRendered)
            return false;
        const [width, height] = widget.get_transformed_size();
        const [x, y] = widget.get_transformed_position();
        const left = """ + str(left) + "; const top = " + str(top) + """;
        // The source clamps to the monitor. These in-bounds preferences must
        // fit, or this scenario cannot demonstrate each independent movement.
        return width + left <= monitor.width && height + top <= monitor.height &&
            Math.abs(x - (monitor.x + left)) <= 1 &&
            Math.abs(y - (monitor.y + top)) <= 1;
        """,
    )


@then("no SJC Gold desktop card remains in the Shell actor tree")
def sjc_card_was_removed(context):
    _wait_for_sjc(context, "return cards.length === 0;")


_SJC_MISSING_CURL_CFFI_STUB = """#!/usr/bin/env python3
# Test fixture: reproduce the source's documented ImportError branch for
# the missing curl_cffi dependency. Mirrors the real handler at
# sjc_price.py:18-30 — same JSON shape and exit code, so the JS sees the
# exact same response as a stock guest without curl_cffi installed.
import json
import sys

print(json.dumps(
    {
        "error": (
            "Chưa cài curl_cffi. Chạy: python3 -m pip install --upgrade curl_cffi"
        ),
        "buy": None,
        "sell": None,
    },
    ensure_ascii=False,
))
sys.exit(1)
"""


def _restore_sjc_helper(stub_path, backup_path):
    if backup_path is not None and Path(backup_path).exists():
        shutil.move(str(backup_path), str(stub_path))


def _sjc_install_helper_stub(context):
    info = context.extension.command(["gnome-extensions", "info", context.extension.uuid]).stdout
    package_path = installed_path(info)
    helper = package_path / "sjc_price.py"
    if not helper.exists():
        raise AssertionError(f"SJC Gold helper missing in installed package: {helper}")
    backup = helper.with_name(helper.name + ".test-backup")
    if backup.exists():
        raise AssertionError(f"Previous SJC helper backup leaked: {backup}")
    shutil.move(str(helper), str(backup))
    helper.write_text(_SJC_MISSING_CURL_CFFI_STUB, encoding="utf-8")
    helper.chmod(0o755)
    context.extension_cleanups.append((_restore_sjc_helper, (helper, backup)))


@given("the SJC Gold Python helper is replaced with a missing curl_cffi stub")
def sjc_helper_replaced_with_missing_dependency(context):
    _sjc_install_helper_stub(context)


_SJC_ERROR_TEXT_PROBE = """
    const cardRendered = card !== null && rendered(card);
    const errorLabel = card ? descendants(card).find(a => hasClass(a, 'sjc-error-text')) : null;
    const errorVisible = !!errorLabel && rendered(errorLabel) && errorLabel.visible !== false;
    const errorText = errorLabel ? errorLabel.text : '';
    return {cardRendered, errorVisible, errorText};
"""


@then("the SJC Gold card renders the actionable missing-curl_cffi error text")
def sjc_card_renders_dependency_error(context):
    expected = "Chưa cài curl_cffi. Chạy: python3 -m pip install --upgrade curl_cffi"
    context.extension.wait_for(
        "(() => { " + _SJC_ACTORS
        + " const probe = (function () {" + _SJC_ERROR_TEXT_PROBE + "})();"
        + " return probe.cardRendered && probe.errorVisible &&"
        + " probe.errorText.includes(" + json.dumps(expected) + "); })()",
        timeout=20,
    )


@step("no SJC Gold helper or python child process remains for the candidate")
def sjc_no_owned_processes(context):
    assert_no_guest_owned_processes(context, ("sjc_price.py",))
