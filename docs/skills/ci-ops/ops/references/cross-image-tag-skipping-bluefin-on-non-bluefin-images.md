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

The smoke suite skips scenarios tagged `@bluefin` unless the image under test
ships Bluefin's common desktop layer. The common suite also runs its shared
`@bluefin` contract scenarios on Dakota, while `@bluefin_classic` marks
assertions that still require Bluefin-classic defaults. Both environments use
`tests/shared/image_family.py`.

Read `BASE_IMAGE` before `IMAGE`: composed runs replace `IMAGE` with
`ghcr.io/<owner>/testsuite-e2e:run-<id>`, which carries no family. Match only
the image-name component, not the org: `projectbluefin` contains `bluefin`, so a
URL-wide check would select Bluefin scenarios on Dakota.

Bluefin-family names are `bluefin`, `bazzite`, `utah`, and `common`. Common's PR
e2e image is named `common`, but it overlays common's `shared` and `bluefin`
trees onto its base image. Utah is Bluefin built on Fedora Hummingbird. Dakota
remains separate and selects `@dakota_only` scenarios. In the common suite,
`@skip_utah` excludes a `@bluefin` scenario on Utah only: it marks content that
Bluefin's common pin still ships but Utah's newer pin does not (the Searchlight
dconf scenario, until #1076 replaces it). Use `@bluefin_classic` for a
common-suite assertion that Dakota deliberately does not ship, such as a
Bluefin-only MIME handler or ujust recipe.

Desktop defaults split differently from the common layer. The Dakota family
(`dakota`, `utah`; `is_dakota_family_image()`) follows Dakota's desktop
defaults, including its eleven default-enabled GNOME Shell extensions
(projectbluefin/utah#1252). In the smoke suite, `@dakota_family` selects those
scenarios (the default-enabled half of `dakota_extensions.feature`), and
`@bluefin_classic` skips scenarios that assert Bluefin-classic defaults, such as
`bluefin_new_extensions.feature` and `copyous_stress.feature`. Utah keeps
running every other `@bluefin` scenario. When a Bluefin scenario asserts an
extension is *enabled* by default, check Dakota's
`disable-ext-validator.bst`; if the extension is not in it, tag the scenario
`@bluefin_classic`.

The smoke suite runs inside the GUI runner container, so it only sees
`BASE_IMAGE` if `e2e.yml` passes it into that container (`-e BASE_IMAGE` and
`-D image=`). Without them, composed smoke runs still report the run-scoped ref
and skip every `@bluefin`, `@dakota_only` and `@dakota_family` scenario.
