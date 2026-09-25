---
name: results-json-crash-tolerance
description: "Deep dive: load_report salvages a results.json truncated by a mid-run crash"
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Results Json Crash Tolerance

## A crashed lane leaves a truncated results.json

behave's JSON formatter writes each completed feature in `eof()` but appends the
closing `]` of the top-level array only in `close()`. A lane that crashes mid-run
therefore leaves a `results.json` that is valid JSON for the features captured so
far but is missing the footer. The possible shapes:

- `[` plus N complete feature objects and no closing `]` (crash between the last
  feature's `eof()` write and `close()`).
- N complete objects plus a truncated final object (crash mid-write of the last
  feature).
- A trailing comma with no following object (`[...,]` → `[,...,`).
- An empty or 0-byte file (nothing was written).

An unguarded `json.loads()` on any of these raises `JSONDecodeError`, which fails
the summarise step for the wrong reason — a crash / "No results generated" — instead
of reporting the real pass/fail state. This is exactly the failure in
projectbluefin/testsuite#604, where a GUI smoke lane mid-run crash produced a
truncated `results.json` and the summarize step's `json.loads` raised.

## `load_report()` salvages the complete objects

`load_report()` in `scripts/e2e_summary.py` is the crash-tolerant entry point:

```python
def load_report(text: str) -> list[dict[str, Any]]:
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        report = _salvage_partial(text)
    return report if isinstance(report, list) else []
```

On a clean document it returns exactly what `json.loads` would — the normal case is
byte-identical to the old `json.loads(results_file.read_text())`. On a
`JSONDecodeError` it delegates to `_salvage_partial()`, which walks the array with
`JSONDecoder.raw_decode()` and collects every complete feature object while dropping
any truncated tail:

```python
def _salvage_partial(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    pos = 0
    length = len(text)
    report: list[dict[str, Any]] = []
    while pos < length:
        while pos < length and text[pos].isspace():
            pos += 1
        if pos >= length:
            break
        char = text[pos]
        if char == "[" or char == ",":
            pos += 1
            continue
        try:
            obj, end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            break
        report.append(obj)
        pos = end
    return report
```

`load_report()` returns `[]` (never raises) on an empty, whitespace-only, or
non-array document, so the summarise step degrades to a zero-scenario report rather
than crashing. `count_scenarios([])` and `scenario_statuses([])` both return empty
results, so a crashed lane reports "0 scenarios" instead of "No results generated".

## Every reader uses `load_report()`

- `.github/actions/gnome-e2e/action.yml` — the `Summarise results` step replaces
  `json.loads(results_file.read_text())` with `load_report(...)`.
- `Justfile` — the `recent-results` recipe (`count_scenarios(load_report(...))`) and
  the `compare-results` recipe (`scenario_statuses(load_report(...))`).
- `scripts/e2e_summary.py` `main()` — the CLI reads
  `load_report(args.results_json.read_text())`.

The behaviour is unit tested in `tests/unit/test_e2e_summary.py` (`test_load_report_*`).
