---
name: gnomeos-desktop-canary
description: "Build and exercise a native GNOME OS desktop test overlay without candidate extensions"
metadata:
  type: reference
  audience: agents
  maturity: draft
---
# GNOME OS desktop canary

This experiment addresses provisioning and desktop automation in #908. It is
not the extension service and cannot close #908 by itself. A build or YAML
check does not establish a boot; inspect actual run artifacts before making
any GNOME OS validation claim.

## Run

Use the Actions UI for `GNOME OS desktop canary` on the desired ref, or:

```bash
gh workflow run gnomeos-canary.yml --repo YOUR_FORK/testsuite --ref YOUR_BRANCH
```

The workflow must first exist on the repository's default branch for GitHub
to register manual dispatch. It also supports `workflow_call` from an existing
workflow for fork experiments. It requests only `contents: read`, publishes no
image, and uses no registry credentials. It is never scheduled automatically.

On a Linux host with rootful Podman, Skopeo, curl, Python and KVM:

```bash
sudo bash scripts/build-gnomeos-harness.sh results
```

This builds `localhost/gnomeos-harness:canary`; it does not boot it. Call the
repository's `gnome-e2e` action with that image and `suite: gnomeos-canary` to
provision and run it, as the workflow does. No raw-image URL or substitute
distribution is involved. The official OCI channel is for development/testing;
GNOME's supported distribution channel remains DDI/sysupdate.

## Evidence contract

Download `gnomeos-desktop-canary` from the run:

- `harness-provenance.json`: official runtime/devel digest references, verified
  Ponytail source hash, and local harness image ID (not a published digest).
- `harness-image-inspect.json`: built image metadata. Failed builds retain
  attempted provenance with a null harness ID.
- `guest-provenance.json`: mounted deployment identity and prerequisite results.
- `bootc-install.log` and `vm-serial.log`: installation and actual boot evidence.
- `desktop-canary.json`: observed build identity, Shell/GJS version, Mutter
  version from the matching development build, session/AT-SPI addresses, random
  expected text and text read through AT-SPI.
- `desktop-canary.png`, Behave results, and `guest-journal.txt`.

The base and development image must name the same GNOME build commit; a
publication race fails the build rather than mixing libraries. The source
archive checksum is enforced both before the build and inside it. The final
image verifies native library linkage and Python imports. It contains a test
overlay, so describe it as GNOME OS **with a harness**, never stock GNOME OS.

The canary requires an empty extension inventory. It cannot be repurposed to
validate candidate code with the current administrative desktop account. The
mandatory result gate rejects missing results, empty/all-skipped runs and
hook/step errors. The canary itself rejects a non-GNOME-OS identity, unknown
build, non-Wayland session or an accessibility address that is merely the
session-bus fallback. Its child process is bounded to 90 seconds, including
Ponytail connection waits.

## Upstream contracts

- [GNOME OCI contribution guide](https://gnome.pages.gitlab.gnome.org/gnome-build-meta/docs/contributing-oci.html):
  official runtime/devel images and development-only bootc use.
- [Ponytail 0.0.11 source](https://gitlab.gnome.org/ofourdan/gnome-ponytail-daemon/-/tree/0.0.11):
  Meson install paths and the window connection/keysym API.
- [GTK Entry](https://docs.gtk.org/gtk3/class.Entry.html): native entry and
  accessibility implementation. No text-setting API supplies the probe value.

When Context7 is unavailable, check these upstream documents and the pinned
Ponytail/qecore source before changing their API calls. Keep native GUI imports inside the guest probe so local dry runs and
unit tests do not require a live desktop.
