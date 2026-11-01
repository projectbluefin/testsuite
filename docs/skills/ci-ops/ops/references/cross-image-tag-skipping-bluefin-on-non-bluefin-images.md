---
name: cross-image-tag-skipping-bluefin-on-non-bluefin-images
description: "Deep dive: Cross-image tag skipping: @bluefin on non-bluefin images"
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Cross Image Tag Skipping Bluefin On Non Bluefin Images

## Cross-image tag skipping: @bluefin on non-bluefin images

The common and smoke suites skip scenarios tagged `@bluefin` unless the image
under test ships Bluefin's common desktop layer. Both environments use
`tests/shared/image_family.py`.

Read `BASE_IMAGE` before `IMAGE`: composed runs replace `IMAGE` with
`ghcr.io/<owner>/testsuite-e2e:run-<id>`, which carries no family. Match only
the image-name component, not the org: `projectbluefin` contains `bluefin`, so a
URL-wide check would select Bluefin scenarios on Dakota.

Bluefin-family names are `bluefin`, `bazzite`, `utah`, and `common`. Common's PR
e2e image is named `common`, but it overlays common's `shared` and `bluefin`
trees onto its base image. Utah is Bluefin built on Fedora Hummingbird. Dakota
remains separate and selects `@dakota_only` scenarios.

The smoke suite runs inside the GUI runner container, so it only sees
`BASE_IMAGE` if `e2e.yml` passes it into that container (`-e BASE_IMAGE` and
`-D image=`). Without them, composed smoke runs still report the run-scoped ref
and skip every `@bluefin` and `@dakota_only` scenario.
