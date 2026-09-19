---
name: fedora-version-targets
description: "Deep dive: Fedora version targets"
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Fedora Version Targets

## Fedora version targets

Three Fedora versions appear in this repo. They are not interchangeable.

| Context | Fedora version | Why |
|---|---|---|
| **`behave --dry-run` CI container** (`pr-validate.yml`) | `fedora:41` (pinned digest) | qecore/dogtail/GObject ABI target; PyGObject from Ubuntu breaks |
| **Test runner image** (`container/Containerfile.runner`) | `fedora-minimal:latest` (rebuilt weekly) | Base for the runner container shipped to the VM |
| **OS under test (gnomeos)** | `gnomeos-latest` (≈ Fedora 44 / GNOME 50) | `quay.io/gnome_infrastructure/gnome-build-meta` |
| **OS under test (Bluefin)** | Fedora 41 based (stable/gts/lts) | Do NOT test against F42 — Bluefin does not ship it |

**Never use F42**: no Bluefin or Bazzite image is based on Fedora 42.

## GNOME 51 readiness (#826)

`gnomeos-latest` tracks upstream and rolls from GNOME 50 to 51 **without any
signal in this repo**. Before the flip, validate against a GNOME 51 tag
(`gnomeos:51.rc` / `51.0` from `quay.io/gnome_infrastructure/gnome-build-meta`)
via a `manual.yml` run of the `vanilla-gnome` and `software` suites, then record
the pass/fail deltas here and in the `vanilla-gnome` suite-map Notes.

The `vanilla-gnome` suite carries an informational `ShellVersion` canary step
(`GNOME Shell version is reported`) that prints the running
`org.gnome.Shell ShellVersion` D-Bus property to the run log. It never gates the
run — its only job is to give signal the moment `gnomeos-latest` flips to 51 so
failures read as a version change rather than an unexplained regression. Update
this row's GNOME version once the flip lands.

---
