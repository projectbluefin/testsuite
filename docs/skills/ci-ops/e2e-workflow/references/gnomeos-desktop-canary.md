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

To test a contributor's pull request without a maintainer copying its code
onto a branch here first, pass the pull request's head commit as `test_ref`
and dispatch from `main`. The canary checks out that commit:

```bash
gh workflow run gnomeos-canary.yml -R projectbluefin/testsuite --ref main -f test_ref=<sha>
```

An empty `test_ref` (the default) tests the commit the workflow was dispatched
from, exactly as before.

The workflow already exists on the repository's default branch, so GitHub
offers manual dispatch directly from any ref (including a fork PR branch).
It also supports `workflow_call` from an existing workflow for fork
experiments. It requests only `contents: read`, publishes no image, and uses
no registry credentials. It is never scheduled automatically.

Because the canary runs the pull request's own scripts and its `gnome-e2e`
action on the runner, read the pull request's diff first. The workflow keeps
`contents: read` and uses no secrets, so checking out an untrusted head gives
it no write access or credentials.

It runs on `ubuntu-24.04`, not `ubuntu-latest`: on 26.04 runners bootc's
loopback install fails with "root partition 3 has type <none>" (#1123). The
`gnome-e2e` action resolves its own repository and ref in a run step before
checking out testsuite, because inside the checkout step
`github.action_repository` names `actions/checkout` (canary run 42919533096
failed with "not our ref" for that reason).

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

The disposable overlay starts GNOME Shell with `--unsafe-mode` so the canary's
ordinary `gdbus` caller can use `org.gnome.Shell.Screenshot`. Setting unsafe mode
through `Shell.Eval` after startup cannot bootstrap this permission. The build
inspects the pinned runtime's Shell user service, preserves its `ExecStart`
arguments (including `--mode=%i` in newer template units), and adds a systemd
drop-in. A missing unit or unknown executable fails the build. This also enables
`Shell.Eval` inside the disposable guest; never apply the overlay to a normal
desktop or treat it as isolation for candidate code.

Upstream's [Shell service template](https://github.com/GNOME/gnome-shell/blob/main/data/org.gnome.Shell%40.service.in)
and [screenshot sender checks](https://github.com/GNOME/gnome-shell/blob/main/js/ui/screenshot.js)
explain the startup and permission contracts. Unit layouts can change; inspect
the build's `Canary Shell startup` log before relying on a new pinned image.

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
hook/step errors. The applicable mandatory gate for this suite is
`Gate extension-validation run`; the more general
`Gate suite has passing scenarios` gate explicitly excludes the GNOME OS
canary. The canary itself rejects a non-GNOME-OS identity, unknown build,
non-Wayland session or an accessibility address that is merely the
session-bus fallback. Its child process is bounded to 90 seconds. Ponytail's
own client waits for its `Connected` and `Disconnected` signals with no
timeout, so the probe calls the daemon's D-Bus methods itself and waits at
most 15 seconds for each signal. `desktop-canary.json` records the `stage`
the probe reached, and a stall prints `gnomeos-canary stuck at <stage>`. The
daemon is D-Bus activated with `G_MESSAGES_DEBUG=all`, so the guest journal
shows what happened to each injected event.

The probe types XKB keycodes, not keysyms. Ponytail 0.0.11 sends a bogus key
0 before every unmodified keysym (its modifier guard tests the wrong
variable), which the shell logs as `Unknown/invalid virtual device key 0x0
pressed`; the real key still follows, so Escape works.

A GNOME session starts in the Activities overview. Keys typed into a window
that was mapped under the overview and focused by pressing Escape never
arrived, whether through IBus or GTK's simple input context (runs
43334774167 and 43337304054). A window opened after the overview was gone
took focus by itself and received the same keys exactly. So the probe first
opens a throwaway window, presses Escape to leave the overview, closes it,
and then types once into a fresh canary window on the plain desktop
(`overview` and `focus` in the evidence say how each got focus). The entry
uses the session's normal input method; its state is recorded as
`input_method`.

### Session environment under qecore-headless

qecore-headless 4.19.3 clears its own environment and rebuilds it from the
first `gnome-session` process's environ plus a short allowlist, then runs the
script with `bash -c`. That environ has no `WAYLAND_DISPLAY` and no usable
session bus, so anything the action exported over SSH is lost and the canary
failed with "Missing Wayland display" (#1144). A `~/.config/environment.d`
drop-in doesn't help: it feeds the systemd user manager, not the GDM-started
session leader that qecore reads.

So for this suite the action runs behave through
`scripts/gnomeos_canary_behave.py`. After qecore's GDM restart, the wrapper
reads `WAYLAND_DISPLAY` from `systemctl --user show-environment`, falling back
to the `wayland-N` socket in `/run/user/<uid>`. It reads the accessibility
bus address from `org.a11y.Bus.GetAddress`, exports those with
`XDG_RUNTIME_DIR` and the session bus, and execs behave. qecore requires the
script's first word to be an executable, so the action calls the wrapper
through the harness Python (`/opt/gnomeos-harness/bin/python3`). The wrapper
waits up to 60 seconds for the restarted shell, then execs anyway, so a
missing value is reported by the canary's own first step.

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
