---
name: dashboard-metrics
version: "1.0"
last_updated: "2026-07-28"
id: dashboard-metrics
one_line_purpose: Read and extend the live testsuite dashboard metrics.
entry_point: docs/skills/ci-ops/dashboard-metrics/SKILL.md
category: ci-ops
mcp_compliance_level: partial
status: active
dependencies: []
tags: [dashboard, metrics, astro, telemetry]
description: "How to read and contribute to the live test dashboard metrics. Load when updating metrics collection or interpreting dashboard data."
metadata:
  type: pattern
  audience: agents
  maturity: stable
---
# QA Dashboard & Metrics compilation

## Overview
This skill guides agents through modifying, compiling, and deploying the QA dashboard located in `dashboard/` and managing its serverless static-site data pipelines.

## When to Use
- Modifying Astro page components (`index.astro`, `run/[id].astro`, headers, layouts, logs viewer)
- Adjusting the python compilation pipeline (`compile_data.py`, `convert_behave.py`)
- Troubleshooting Pagefind search indexing or broken CSS asset paths on the custom domain
- Updating pages deployment actions (`publish-to-pages.yml`)

## When NOT to Use
- Writing or debugging GDM/AT-SPI behave test scenarios inside `tests/**` — use `gnome.md` or `behave.md`
- Modifying Argo/KubeVirt cluster infrastructure manifests — use `projectbluefin/lab` repo
- Adjusting core reusable workflow configurations (`e2e.yml`) — use `e2e-workflow.md`

## Core Process

1. **Path-Robust Script Design**: When writing python aggregation or data conversion scripts under `dashboard/scripts/`, never hardcode relative string paths like `./raw-runs` or `./src/data/`. Execution directories differ between local development and CI runs. Always resolve path coordinates dynamically relative to the script's actual directory:
   ```python
   from pathlib import Path
   SCRIPT_DIR = Path(__file__).resolve().parent
   DASHBOARD_DIR = SCRIPT_DIR.parent
   RUNS_DIR = DASHBOARD_DIR / "src" / "data" / "runs"
   ```

2. **Build-Time Compilation Power**: Take full advantage of Astro's build-time static generation. Instead of loading logs client-side at runtime, import raw run JSONs in the frontmatter of your Astro pages using Vite globbing:
   ```typescript
   const runFiles = import.meta.glob('../data/runs/*.json', { eager: true });
   const runs = Object.entries(runFiles).map(([path, content]: [string, any]) => ({
     id: path.split('/').pop().replace('.json', ''),
     ...(content.default || content)
   }));
   ```
   Compute aggregations, pass rates, trend lists, and top failing scenarios during the static build, resulting in instant load times for users.

3. **Inline Script Bypasses**: Astro typechecks `<script>` blocks by default. To prevent TypeScript compiler errors (such as `Property 'style' does not exist on type 'Element'`) when writing standard client-side vanilla JavaScript, use the `is:inline` Astro directive:
   ```html
   <script is:inline>
     // Vanilla JS runs verbatim on client-side with no strict TS compilation checks
     document.querySelectorAll('.items').forEach(el => el.style.display = 'none');
   </script>
   ```

4. **Client-Side Telemetry Fetching**: To integrate live, dynamic infrastructure status (like KubeVirt node states and active semaphore VM slots) that change rapidly, fetch the latest compiled JSON from raw GitHub Pages endpoints, and implement an offline-safe local fallback `SEED` dataset:
   ```javascript
   const TELEMETRY_URL = "https://raw.githubusercontent.com/projectbluefin/lab/main/docs/data/factory-stats.json";
   async function getLiveTelemetry() {
     try {
       const res = await fetch(TELEMETRY_URL);
       const stats = await res.json();
       updateNodesDOM(stats);
     } catch (e) {
       console.warn("Fallback to offline dataset:", e);
     }
   }
   ```

5. **Build-Time SSG Data Fetching (Astro Frontmatter)**: For high-performance landing page rendering with zero dynamic scraping lag, fetch external JSON datasets (like `factory-stats.json` or individual suite JSON files) during build time inside Astro's frontmatter blocks. This converts raw runtime REST fetching into statically pre-rendered HTML cards, tables, and charts:
   ```typescript
   // src/pages/index.astro
   const statsRes = await fetch('https://projectbluefin.github.io/lab/data/factory-stats.json');
   const stats = statsRes.ok ? await statsRes.json() : {};
   ```

6. **Node-Based Markdown Skills Loader**: Standard Astro Content Collections cannot access files located outside the dashboard's `src/` folder (such as standard repository documentation in `docs/skills` or a sibling repository like `../common/docs/skills`). Bypass this restriction by writing a dynamic build-time filesystem loader in `src/utils/getSkills.js` using a small `parseFrontMatter()` splitter that extracts the leading `---` block and parses it with `js-yaml` (default safe schema), plus `marked` for Markdown rendering. Do not add `gray-matter`.

7. **Pagefind Search Indexing for Dynamically Loaded Skills**: Enable Pagefind search on dynamically loaded Markdown files by adding `data-pagefind-body` directly on the `<main>` or `<article>` element containing the rendered skill body, and use Pagefind metadata selectors (such as `data-pagefind-meta="category"`) to expose tags to the client-side search component.

8. **Site path — served from `https://projectbluefin.github.io/testsuite/`**: The dashboard is deployed to the `gh-pages` branch and served from the repository subpath `https://projectbluefin.github.io/testsuite/`. `astro.config.mjs` MUST keep `base: '/testsuite/'` and `site: 'https://projectbluefin.github.io'` so that absolute asset paths resolve under `/testsuite/`. Do not set `base: '/'` — on a GitHub Pages subpath that drops the `/testsuite/` prefix and 404s all CSS and Pagefind assets.

9. **Do NOT write a CNAME on deploy**: The dashboard is served from `https://projectbluefin.github.io/testsuite/`, not from a custom domain. The org zone maps `qa.projectbluefin.io` to a redirect Worker (the zone hostname policy 301s it to `https://factory.projectbluefin.io/`), so any `CNAME` written to the `gh-pages` branch claims a name that no longer serves this site and 404s. `publish-to-pages.yml` must NOT write a `CNAME` file. The `base: '/testsuite/'` in `astro.config.mjs` is what makes the subpath work — not a CNAME.

10. **Tailwind v4 via `@tailwindcss/vite` (no Astro integration)**: The dashboard uses Tailwind CSS v4 through the official Vite plugin (`@tailwindcss/vite`), declared in `astro.config.mjs` under `vite.plugins`, plus `@import "tailwindcss";` in `src/styles/global.css` (loaded via a `<style is:global>` block in `src/layouts/Layout.astro`). Custom design tokens live in the CSS `@theme` block in that file, not in a `tailwind.config.*` file — v4 is CSS-first, so config-file content globbing is gone. The deprecated `@astrojs/tailwind` integration (which capped `astro` at v5 via `peer astro@"^3.0.0 || ^4.0.0 || ^5.0.0"` and froze the `vite`/`esbuild`/`sharp` patch stream) must not be re-added. With the cap gone, `renovate.json` no longer constrains the astro major; validate any astro major bump locally with `cd dashboard && rm -rf node_modules && npm ci && npm run build` — `npm install` alone is not sufficient, because it resolves differently than `npm ci`.

11. **`publish-to-pages.yml` is not exercised by PR checks**: the workflow only triggers on `schedule`, `workflow_dispatch`, and pushes to `main` under `dashboard/**`. A dependency PR can therefore merge fully green and only break the dashboard hours later on the next 2-hourly cron. Any PR touching `dashboard/package.json`, `dashboard/package-lock.json`, or `dashboard/scripts/**` must be validated locally with `npm ci && npm run build` before merge.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I will hardcode `./raw-runs` in my script since I am running it from the root." | Someone else or the GHA run will execute it from another folder and fail with a directory mismatch. Always resolve paths relative to the script location. |
| "Astro should fetch all logs from a remote database in the browser." | Fetching hundreds of logs in client-side JS introduces major latency. Compiling them statically at build-time using `import.meta.glob` is faster and completely serverless. |
| "The CNAME to qa.projectbluefin.io must be preserved on every deploy." | qa.projectbluefin.io is a redirect, not this site's domain. Writing CNAME claims a name that 301s away and 404s. Never write CNAME — serve from https://projectbluefin.github.io/testsuite/ via base: '/testsuite/'. |
| "A dependency bump PR is green, so the dashboard still builds." | `publish-to-pages.yml` never runs on pull requests. Green PR checks say nothing about `npm ci`; run it locally before merging any `dashboard/` dependency change. |

## Behave converter CLI

`dashboard/scripts/convert_behave.py` takes seven operands: the input JSON,
run ID, caller repository, slug, suite, timestamp, and output directory.
That means eight `sys.argv` entries including the script name. With fewer
operands it prints usage and exits 1 before reading input or creating output.
`tests/unit/test_convert_behave_cli.py` covers zero through six operands and
successful conversion with all seven; the six-operand case catches an
otherwise easy-to-miss off-by-one in the guard.

### Per-test status and error text

Each `tests[]` entry carries the normalized scenario status — `passed`,
`failed` or `skipped` — matching the summary bucket it was counted in.
`LogViewer.astro` draws `skipped` grey and collapsed; collapsing it into
`failed` once rendered every `@pending`/`@future` scenario as a red failure
under a SUCCESS badge. behave writes a multi-line `error_message` (every
traceback) as a list of lines, so `error_text()` joins it before it reaches
the log or the `error_message` field, the same rule as
`scripts/e2e_summary.py:error_text`.

## Coverage badges: `scripts/generate_badges.py`

The shields.io coverage badges are generated at publish time by parsing
`.feature` files under `tests/*/features/`. No counts are hardcoded, so the
badges always track current test content.

Every scenario lands in exactly one of three buckets, evaluated in this order:

1. **stub** — tagged `@future` *or* `@pending`
2. **quarantined** — tagged `@quarantine` (at feature or scenario level)
3. **active** — everything else

`@pending` counts as a stub, not as active. Both tags mean "written but not
running", and the badge already renders this bucket as `N pending`, so
excluding `@pending` inflated the active count and under-reported stubs.

Order matters: the stub check runs first, so a scenario tagged both `@future`
and `@quarantine` is reported as a stub. Adding a new "not running yet" tag
means updating `count_scenarios()` — otherwise those scenarios are silently
counted as active.

## Red Flags
- Setting `base: '/'` in `astro.config.mjs` while deploying to `https://projectbluefin.github.io/testsuite/` (drops the `/testsuite/` prefix and 404s CSS and Pagefind assets).
- Writing a `CNAME` file in `publish-to-pages.yml` (claims qa.projectbluefin.io, which redirects away and 404s).
- Adding complex TypeScript type assertions inside a vanilla JS client-side script tag when `<script is:inline>` would safely bypass them.
- Creating static aggregations that fail silently when a directory is empty instead of logging a meaningful exception.

## Verification
- [ ] Astro build passes with **0 errors and 0 warnings**: `cd dashboard && npm run build`
- [ ] Pagefind client-side search index is compiled successfully.
- [ ] Path resolution in Python scripts works correctly from any folder directory.
- [ ] `publish-to-pages.yml` does NOT write a `CNAME` file, and the dashboard loads (200, CSS + Pagefind assets) at `https://projectbluefin.github.io/testsuite/`.
- [ ] After the first CNAME-less deploy, the repository Pages custom domain is empty: `curl -sI https://projectbluefin.github.io/testsuite/` must return `200`, not a `301` to `qa.projectbluefin.io`. GitHub normally clears the custom-domain setting when `CNAME` disappears from the publishing branch; if the redirect persists, clear the domain by hand in **Settings → Pages → Custom domain**, otherwise the `github.io` URL keeps forwarding to a host that no longer serves this site.
