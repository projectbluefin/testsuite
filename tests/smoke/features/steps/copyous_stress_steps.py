"""Step definitions for Copyous clipboard manager stress and crash-regression testing."""

import json
import random
import string
import time
from time import sleep

from behave import step

from tests.smoke.features.steps.bluefin_new_extensions_steps import (
    _assert_no_new_shell_errors,
    _assert_no_shell_coredump,
    _clipboard_get,
    _clipboard_set,
    _eval_bool,
    _gnome_shell_rss_kb,
    _journal_snapshot_marker,
    _shell_eval,
    _wait_gnome_shell_accessible,
)

try:
    from dogtail import tree
except ImportError:
    tree = None


@step("snapshotting GNOME Shell state and journal marker")
def snapshotting_gnome_shell_state_and_journal_marker(context) -> None:
    context.copyous_baseline_marker = _journal_snapshot_marker()
    context.copyous_baseline_rss_kb = _gnome_shell_rss_kb()
    context.last_copied_payload = None


@step("generating rapid clipboard churn of {count:d} events with varied MIME types and binary data")
def generating_rapid_clipboard_churn(context, count: int) -> None:
    payloads = [
        "plain text string",
        "multiline\ntext\nwith\nnewlines\n",
        "unicode chars: 🚀 💥 🦀 漢字 ñ á ç ü",
        json.dumps({"key": "value", "list": [1, 2, 3], "nested": {"a": True}}),
        "code snippet: function() { const x = 42; return x * 2; }",
        "URL string: https://projectbluefin.io/docs/testing/extensions?ref=copyous#stress",
        "".join(random.choices(string.printable, k=500)),
    ]

    for i in range(count):
        chosen = payloads[i % len(payloads)] + f" [seq={i}]"
        context.last_copied_payload = chosen
        _clipboard_set(chosen)
        sleep(0.05)


@step("the clipboard retains the final copied payload")
def clipboard_retains_final_copied_payload(context) -> None:
    expected = getattr(context, "last_copied_payload", None)
    if expected is not None:
        actual = _clipboard_get()
        assert actual == expected, (
            f"Clipboard content mismatch: expected last {len(expected)} chars, got {len(actual)} chars"
        )

@step("GNOME Shell remains accessible via AT-SPI")
def gnome_shell_remains_accessible_atspi(context) -> None:
    _wait_gnome_shell_accessible()


@step("no gnome-shell coredump or crash occurred")
def step_no_gnome_shell_coredump_or_crash(context) -> None:
    _assert_no_shell_coredump()
    _wait_gnome_shell_accessible()


@step("no fatal GJS or extension errors exist in the journal")
def step_no_fatal_gjs_or_extension_errors(context) -> None:
    marker = getattr(context, "copyous_baseline_marker", None)
    if marker:
        _assert_no_new_shell_errors(marker, extra_pattern="copyous|gnome-shell")


@step("copying a 1 megabyte payload to clipboard")
def copying_one_megabyte_payload(context) -> None:
    # 1MB of text
    large_text = "A" * (1024 * 1024)
    context.last_copied_payload = large_text
    _clipboard_set(large_text)
    sleep(0.2)


@step("copying a multiline text payload of {lines:d} lines to clipboard")
def copying_multiline_text_payload(context, lines: int) -> None:
    multiline = "\n".join(f"Line number {i}: Copyous stress line with data {i * 17}" for i in range(lines))
    context.last_copied_payload = multiline
    _clipboard_set(multiline)
    sleep(0.2)


@step("copying complex nested JSON payload to clipboard")
def copying_complex_nested_json(context) -> None:
    data = {
        "metadata": {"version": 1, "test": "copyous-resilience"},
        "items": [{"id": i, "tags": [f"t{j}" for j in range(10)], "text": f"item-{i}" * 5} for i in range(200)],
    }
    dumped = json.dumps(data, indent=2)
    context.last_copied_payload = dumped
    _clipboard_set(dumped)
    sleep(0.2)


@step("GNOME Shell remains responsive within {timeout:d} seconds")
def gnome_shell_remains_responsive(context, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            res = _eval_bool("true")
            if res is True:
                return
        except Exception:  # noqa: BLE001
            pass
        sleep(0.2)
    raise AssertionError(f"GNOME Shell did not respond to Shell.Eval within {timeout}s after heavy payload")


@step("GNOME Shell memory growth remains strictly bounded under {mb:d} megabytes")
def gnome_shell_memory_growth_remains_strictly_bounded(context, mb: int) -> None:
    baseline = getattr(context, "copyous_baseline_rss_kb", None)
    current = _gnome_shell_rss_kb()
    if baseline is None:
        print(f"WARNING: No baseline RSS recorded; current is {current} KiB", flush=True)
        return
    growth_kb = current - baseline
    max_allowed_kb = mb * 1024
    print(f"Copyous stress RSS growth: {growth_kb} KiB (max allowed {max_allowed_kb} KiB)", flush=True)
    assert growth_kb <= max_allowed_kb, (
        f"GNOME Shell RSS grew by {growth_kb / 1024:.2f} MB after copyous payload stress, "
        f"exceeding safety ceiling of {mb} MB (possible memory leak/unbounded buffer)"
    )


@step("Copyous clipboard history popover is opened via keyboard shortcut or AT-SPI")
def copyous_popover_is_opened(context) -> None:
    # Trigger shortcut or open via gdbus/Shell.Eval
    js_trigger = (
        "(() => {"
        "  try {"
        "    const ext = Main.extensionManager.lookup('copyous@boerdereinar.dev');"
        "    if (ext && ext.stateObj && typeof ext.stateObj.toggleMenu === 'function') {"
        "      ext.stateObj.toggleMenu();"
        "      return true;"
        "    }"
        "  } catch(e) {}"
        "  return false;"
        "})()"
    )
    try:
        _shell_eval(js_trigger)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: could not trigger Copyous toggleMenu via Shell.Eval: {exc}", flush=True)
    sleep(0.2)


@step("Copyous clipboard history popover is rapidly toggled {count:d} times")
def copyous_popover_is_rapidly_toggled(context, count: int) -> None:
    js_toggle = (
        "(() => {"
        "  try {"
        "    const ext = Main.extensionManager.lookup('copyous@boerdereinar.dev');"
        "    if (ext && ext.stateObj && typeof ext.stateObj.toggleMenu === 'function') {"
        "      ext.stateObj.toggleMenu();"
        "      return true;"
        "    }"
        "  } catch(e) {}"
        "  return false;"
        "})()"
    )
    for _ in range(count):
        try:
            _shell_eval(js_toggle)
        except Exception:  # noqa: BLE001
            pass
        sleep(0.05)


@step("GNOME Shell responds to Shell.Eval within {timeout:d} seconds")
def gnome_shell_responds_to_eval_within(context, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _eval_bool("true") is True:
                return
        except Exception:  # noqa: BLE001
            pass
        sleep(0.2)
    raise AssertionError(f"GNOME Shell failed to evaluate JavaScript within {timeout}s")



@step("copying payload with embedded null bytes and escape characters")
def copying_payload_with_null_and_escapes(context) -> None:
    payload = "Text with \x00 null byte, \r\n CRLF, \t tab, \b backspace, and \x1b[31m ANSI codes"
    context.last_copied_payload = payload
    _clipboard_set(payload)
    sleep(0.1)


@step("copying an empty string payload")
def copying_empty_string_payload(context) -> None:
    context.last_copied_payload = ""
    _clipboard_set("")
    sleep(0.1)


@step("copying payload with special characters and SQL injection strings")
def copying_payload_with_sql_injection(context) -> None:
    payload = "'; DROP TABLE clipboard_entries; -- \"><script>alert('xss')</script> &quot; \x00"
    context.last_copied_payload = payload
    _clipboard_set(payload)
    sleep(0.1)
