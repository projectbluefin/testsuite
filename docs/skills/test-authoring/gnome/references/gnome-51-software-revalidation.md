---
name: gnome-51-software-revalidation
description: "Why the software suite's @future scenarios need relocation before GNOME 51 can validate them, plus the corrected re-validation procedure. Issue #847."
---
# Software-suite `@future` re-validation on GNOME 51 (issue #847)

Working inventory for issue #847, sibling to [gnome-51-audit.md](gnome-51-audit.md)
(issue #827). Every row is **UNVALIDATED**: the only way to move a row to a
classification is a live run on a GNOME 51 image. Do not promote a guess, and do
not delete a scenario on an unvalidated guess.

## Governing facts

- GNOME 51 GA is **2026-09-16**; `gnomeos-latest` rolls to it with no signal in
  this repo. Confirm the running version with the Shell version canary added in
  `tests/vanilla-gnome/features/gnome_core.feature`.
- Bluefin ships **Bazaar** (`io.github.kolunmi.Bazaar`), not upstream
  `org.gnome.Software`. Bazaar's tab strip is `Curated`, `Explore`, `Library`,
  `Search` (`tests/software/features/steps/steps.py:27`) — there is **no
  `Installed` tab**.
- `software` is the only suite that starts a software centre. `vanilla-gnome`
  sandboxes `gnome-shell`, not an application
  (`tests/vanilla-gnome/features/environment.py`), and currently runs no
  software-centre coverage at all.

## The trap: a `software` run on gnomeos validates none of these rows

Issue #828 prescribed "run the software suite against GNOME 51 gnomeos via
`manual.yml`" as the validation step. That run produces no evidence for the six
upstream-GNOME-Software rows, for two independent reasons:

1. `@future` is a **non-runnable tag**: `skip_quarantine()`
   (`tests/shared/quarantine.py:22`) skips the scenario in `before_scenario`
   before any step executes.
2. With `@future` dropped, `before_scenario` still skips every scenario tagged
   `@software` without `@flatpak_cli` on an image that has no Bazaar
   (`tests/software/features/environment.py:112`). gnomeos ships no Bazaar.

Bluefin is the only image carrying Bazaar, and there the scenarios would execute
but fail — they assert the upstream GNOME Software widget model
(`"Explore" "toggle button"`, `"Installed" "toggle button"`, `"Installed" "page
tab"`), while Bazaar exposes the four-tab strip above. #504 already rewrote
Bazaar coverage against the real layout in `bazaar_ui.feature` and
`bazaar_navigation.feature`.

**Consequence:** no image can execute these six scenarios as written. A
gnomeos-51 `software` run reports them `SKIPPED`, which looks like "the GNOME 50
AT-SPI cache error is gone" and is **not** evidence. Never activate a row on the
strength of a skipped run.

## Inventory

7 scenarios carry `@future` (6 in `flatpak.feature`, 1 in `flatpak_cli.feature`);
the eighth item in the issue's inventory is a comment in `bazaar.feature`, not a
scenario.

| # | Scenario | Where | Blocked today by |
|---|---|---|---|
| 1 | Explore tab is present and accessible | `tests/software/features/flatpak.feature:19` | `@future`; upstream widget tree — un-runnable on every image (see trap) |
| 2 | Installed tab is present and accessible | `flatpak.feature:23` | Same, and `Installed` is not a Bazaar tab |
| 3 | Clicking Installed tab shows installed apps list | `flatpak.feature:27` | Same; also asserts an `Installed` `page tab` |
| 4 | Flatpak updates section is reachable without crash (bluefin#4062) | `flatpak.feature:41` | Same; crash guard written against `gnome-software` |
| 5 | No gnome-software coredump on Explore page load (bluefin#4471) | `flatpak.feature:46` | Same; asserts a `gnome-software` coredump Bazaar never produces |
| 6 | Bazaar closes cleanly via shortcut | `flatpak.feature:52` | `@future`; Bazaar close coverage already active in `bazaar_ui.feature` |
| 7 | flatpak install and uninstall round-trip succeeds | `flatpak_cli.feature:25` | `@future`; image-agnostic CLI, deferred for network cost — needs dedicated CI execution, not a GUI run |
| 8 | *(comment)* AT-SPI re-validation note | `bazaar.feature:9` | Pointer to this issue; no scenario |

## Validation procedure (corrected)

1. Before any run, relocate the coverage (see **Escalation**) so the scenarios
   live in a suite that actually starts `org.gnome.Software` on a `gnomeos-51`
   image. Running them as-is yields skips, not results.
2. Boot the GNOME 51 `gnomeos` image
   (`quay.io/gnome_infrastructure/gnome-build-meta`, tag `51.*` /
   `gnomeos-latest`) through the repo's `manual.yml` run workflow. *No image or
   workflow target is available in this agent environment* — this step is lab /
   CI infrastructure, not testsuite.
3. Re-derive the navigation widget model from the live AT-SPI tree first; do not
   carry the GNOME 50 `toggle button` / `page tab` names over. The Shell version
   canary confirms the image really is 51.
4. For each row, classify as one of:
   - **still required** — 51 reproduces the 50 behaviour; keep the workaround.
   - **broken on 51** — 51 diverged and the step now fails; fix the step.
   - **obsolete** — 51 no longer needs it; keep only if Bluefin (50) still does.
5. Row 7 is separable: it needs no GUI and no GNOME version. Schedule it as a
   dedicated CI job rather than folding it into a GUI run.
6. When totals change, run `python3 scripts/update_coverage_snapshot.py` and
   sync `docs/qa-review.md`.

## Escalation

Relocating upstream GNOME Software coverage into a `gnomeos`-capable suite
changes which scenarios a suite runs against a given image, and wiring an
application sandbox into `vanilla-gnome` is new test infrastructure. Both are
**Design gates** (`docs/skills/meta/human-gates/SKILL.md`): stop and request
maintainer approval before moving scenarios between suites or adding the app
sandbox. Until then, the correct state for these rows is `@future` and this
document — not activation.

## Related

- [GNOME 50 workaround audit against GNOME 51 (issue #827)](gnome-51-audit.md)
- [Suite map and coverage](../../suite-map/SKILL.md)
