---
name: inputs-outputs
description: "Workflow inputs, outputs, artifacts, and screenshot handling."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Inputs Outputs

## Flatpak cache pattern for Bluefin GUI suites

`e2e.yml` masks `flatpak-preinstall.service` in `KERNEL_ARGS`, so CI first boot never waits on the image's bulk Flathub pull. When a Bluefin-family GUI suite still needs specific Flatpaks (currently `org.mozilla.firefox` and `io.github.kolunmi.Bazaar`), cache a **user** Flatpak repo on the GHA runner and inject it over SSH after GNOME is up:

1. Add the manifest file (currently `flatpak-app-list.txt`) to the sparse checkout, or both `hashFiles()` and SCP will miss it.
2. Cache `${GITHUB_WORKSPACE}/.flatpak-cache-home/.local/share/flatpak` with `actions/cache`.
3. On a miss, run `flatpak install --user --no-deploy ...` on the runner to download refs/runtimes without deploying them.
4. Copy that repo into the VM, then deploy missing apps system-wide with `sudo flatpak install --system --sideload-repo=<copied repo> ...`, falling back to a normal pull only if the cache is incomplete.

Do **not** preload these apps on non-Bluefin images: that mutates dakota/gnomeos coverage instead of testing what those images actually ship.
## Screenshots and GHCR artifacts

Every e2e run produces a desktop screenshot at end-of-run as visual proof of a working GNOME session.

### Desktop screenshot — two capture paths

**Primary path (in-VM):** `take_fastfetch_screenshot()` is called in `after_all` for every GUI suite. It uses `gnome-screenshot` or `grim` inside the VM and writes to `results/desktop_screenshot.png`.

**Fallback path (QEMU monitor screendump):** If no in-VM screenshot lands (behave crashed, container never started, AT-SPI unavailable), `e2e.yml` captures the QEMU VGA framebuffer directly via the monitor socket at `/tmp/qemu-monitor.sock`. QEMU maintains this framebuffer internally even with `-display none` because mutter uses bochs-drm (card1) as the KMS device, which maps to the VGA framebuffer. The screendump is converted PPM→PNG via Python stdlib (`tests/shared/qemu_screendump.py`).

If **both** paths fail (QEMU monitor socket missing or empty framebuffer), the "Promote desktop screenshot" step fails loud — a missing screenshot from a non-`common` suite is treated as a job failure, not a silent pass.

### Desktop screenshot distribution

After the behave suite finishes, `take_fastfetch_screenshot()` is called in `after_all` for every GUI suite. The screenshot is taken in-VM via AT-SPI/Wayland. If `after_all` was not reached (e.g. the runner container failed to start), the GHA runner falls back to a QEMU monitor screendump: `sudo python3 tests/shared/qemu_screendump.py` sends a `screendump` command to `/tmp/qemu-monitor.sock` (opened at QEMU boot) and converts the PPM output to PNG using the Python stdlib. The "Promote desktop screenshot" step fails loud with `::error::` if neither source produces a file — that failure is intentional and means the container never loaded or behave exited before `after_all`.

The screenshot is:

1. Uploaded to the `e2e-results-*` artifact (as `desktop_screenshot.png` or `screenshot_<suite>_fastfetch_endofrun.png`)
2. Rendered inline in the **GitHub Actions job summary**
3. Pushed to GHCR as an OCI artifact:

| Tag | Meaning |
|-----|---------|
| `ghcr.io/projectbluefin/testsuite/desktop-screenshot:<suite>-latest` | Most recent run for that suite, e.g. `:smoke-latest` |
| `ghcr.io/projectbluefin/testsuite/desktop-screenshot:<slug>-<suite>-latest` | Per-image slug tag, e.g. `bluefin-testing-smoke-latest` — used by publish-to-pages |
| `ghcr.io/projectbluefin/testsuite/desktop-screenshot:<short-sha>` | Immutable per-commit tag |

**No `:latest` tag is pushed.** `latest` is not a tag used in this repo — do not add it.

Pull the latest screenshot locally:
```bash
oras pull ghcr.io/projectbluefin/testsuite/desktop-screenshot:smoke-latest
```

### gh-pages screenshot publishing

**Architecture: schedule-based polling, not workflow_run.**

`workflow_run` only fires for workflows running in the **same repository**. When consumer repos (bluefin, bluefin-lts, dakota) call `e2e.yml` via `workflow_call`, the run is recorded in the **caller's** repo — testsuite's `workflow_run` never fires. The metadata-artifact handoff approach is dead for cross-repo calls.

The working approach:

1. **`e2e.yml` pushes a slug-specific GHCR tag per run** alongside the existing suite tag:
   ```
   ghcr.io/projectbluefin/testsuite/desktop-screenshot:<slug>-<suite>-latest
   ```
   Slug derivation: canonically owned by `scripts/image_slug.py` (`get_image_slug()`).
   Strips registry host (e.g. `ghcr.io`, `quay.io`, `docker.io`, `localhost:5000`) and org/namespace,
   folds remaining `/`, `:`, and `@` into `-`, and sanitizes to the OCI tag charset (`[a-zA-Z0-9_.-]`).
   Handles digest-pinned refs (`bluefin@sha256:...` → `bluefin-sha256-...`), non-GHCR registries (`quay.io/.../silverblue:44` → `silverblue-44`), and nested paths (`subgroup/bluefin:latest` → `subgroup-bluefin-latest`).
   In `e2e.yml`, `Capture boot time` and `upload-screenshot` derive via `scripts/image_slug.py "${BASE_IMAGE}"`, and `Write job summary` consumes `steps.upload-screenshot.outputs.image_slug` with fallback to `get_image_slug()`.
   Example: `ghcr.io/projectbluefin/bluefin:testing` → `bluefin-testing-smoke-latest`

   **SCREENSHOT_SUITE normalization:** smoke sharding pushes `SCREENSHOT_SUITE=smoke` for both
   `smoke-a` and `smoke-b`. The GHCR tag is always `{slug}-smoke-latest`, never `{slug}-smoke-a-latest`.
   If you add new shards, update the `SCREENSHOT_SUITE` normalization block in e2e.yml and keep
   `SUITES=(smoke common vanilla-gnome)` in `publish-to-pages.yml` unchanged.

   The tag is annotated with `io.github.projectbluefin.run_id` and `io.github.projectbluefin.caller_repo` for JSONL traceability.

2. **`publish-to-pages.yml` runs on a 2-hour schedule** (+ `workflow_dispatch` for manual trigger). It pulls the known slug-specific tags directly from GHCR — no metadata artifacts, no cross-repo auth. JSONL reads `run_id` and `caller_repo` from OCI manifest annotations via `oras manifest fetch`.

Known slugs hardcoded in `publish-to-pages.yml`:
```bash
SLUGS=(bluefin-testing bluefin-lts-testing dakota-testing)
SUITES=(smoke common vanilla-gnome)
```
Add new slugs here when the fleet grows. **Do not add `dx`, `developer`, or `lifecycle` to SUITES** — these suites are not tracked by publish-to-pages (dx/developer run on gdx images not in the SLUGS list; lifecycle is a migration workflow with no desktop screenshots).

**Dashboard source of truth:** The QA dashboard is now a modern Astro static-site project located in the `dashboard/` directory on `main`. Every run of the scheduled `publish-to-pages.yml` workflow checks out the repository, pulls the latest test results and screenshots from GHCR, parses/converts behave logs, aggregates historical statistics, compiles Astro to static HTML, indexes the entire site with Pagefind, and deploys it natively to GitHub Pages.

Never edit files on the `gh-pages` branch directly—always make edits inside the `dashboard/` directory on `main`.

Stable URL format:
```text
https://projectbluefin.github.io/testsuite/screenshots/{slug}-{suite}-latest.png
```

The historical runs are compiled and indexed natively at `qa.projectbluefin.io` (or `https://projectbluefin.github.io/testsuite/`).

### Flatpak screenshot gallery

Set `screenshot_flatpaks` to capture per-app screenshots useful for app authors:

```yaml
uses: projectbluefin/testsuite/.github/workflows/e2e.yml@main
with:
  image: ghcr.io/projectbluefin/bluefin:testing
  suites: smoke
  screenshot_flatpaks: "org.gnome.Calculator,io.github.kolunmi.Bazaar"
```

Each app is launched, held for 3 seconds, then captured. Results pushed to:
`ghcr.io/projectbluefin/testsuite/desktop-screenshot:flatpak-<slug>-latest`

See [`docs/flatpak-screenshots.md`](../../../flatpak-screenshots/SKILL.md) for full documentation.
