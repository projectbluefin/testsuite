---
name: gnomeos-guest-provenance
description: "GNOME OS image provenance (2-week tag expiry), verified guest inventory, and the extensions pre-boot preflight"
metadata:
  type: reference
  audience: agents
  maturity: draft
---
# GNOME OS guest provenance and preflight (#908)

Companion to [gnome-extensions-validation.md](gnome-extensions-validation.md). Everything here
was checked against the published image's layers; **none of it proves a boot.**

## Provenance: pin per run, not in this file

Base image `quay.io/gnome_infrastructure/gnome-build-meta`, tag `gnomeos-nightly` (or
`gnomeos-51` / `gnomeos-50` for a stable branch). **Every `gnomeos-*` tag expires two weeks after
it is pushed** — the image config carries the label `quay.expires-after: 2w`, and the Quay tag API
shows each `gnomeos-nightly` revision with a 14-day `end_ts`. A digest copied into a doc or
workflow is unpullable within a fortnight: the `sha256:57eeef…ed981` pin recorded here on
2026-09-30 returned `MANIFEST_UNKNOWN` by 2026-10-27. Stable-branch tags move too (`gnomeos-51`
was re-pushed three times between 2026-10-25 and 2026-10-27).

So the lane resolves the tag to a digest **at dispatch time**, pulls that digest, and the
`gnome-e2e` action records what it actually installed in `results/guest-provenance.json`:
the image reference, the digest podman resolved, and the guest's `os-release` identity
(`ID=org.gnome.os`, `IMAGE_VERSION`, `GNOMEOS_COMMIT`, the gnome-build-meta commit). That file,
not a doc table, is the provenance record. A long-lived pin would need a mirror into a registry
we control, which is lab infrastructure, not this repo.

```bash
# resolve without pulling (Quay anonymous token)
TOKEN=$(curl -s "https://quay.io/v2/auth?service=quay.io&scope=repository:gnome_infrastructure/gnome-build-meta:pull" | jq -r .token)
curl -sI -H "Authorization: Bearer $TOKEN" \
  -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
  https://quay.io/v2/gnome_infrastructure/gnome-build-meta/manifests/gnomeos-nightly \
  | grep -i docker-content-digest
# or: skopeo inspect docker://quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-nightly | jq -r .Digest
```

### Resolving the digest in a workflow

No workflow does this yet. A sketch of a `resolve` job whose output feeds the `gnome-e2e`
`image:` input (the e2e job declares `needs: resolve`):

```yaml
jobs:
  resolve:
    runs-on: ubuntu-latest
    outputs:
      digest: ${{ steps.digest.outputs.digest }}
    steps:
      - id: digest
        run: |
          d=$(skopeo inspect docker://quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-nightly | jq -r .Digest)
          echo "digest=$d" >> "$GITHUB_OUTPUT"
```

## Guest inventory (verified against the image, not booted)

Inventoried 2026-10-27 from `gnomeos-nightly` @ `sha256:9dd3a858…e824c`
(`IMAGE_VERSION=nightly.20261027.1`, `GNOMEOS_COMMIT=9c38eabc…`) by listing its four OCI layers
(Freedesktop SDK minimal + platform, GNOME SDK platform, GNOME OS) and running
`scripts/guest_preflight.py` over a skeleton of that tree. The image config sets
`containers.bootc=1`.

| `gnome-e2e` step | Needs | GNOME OS nightly |
|---|---|---|
| `bootc install to-disk` | `bootc` in the image | `usr/bin/bootc`, `usr/lib/bootc/install/` ✅ (no `bootupd`; the action already tolerates that) |
| direct QEMU boot | kernel + initramfs in the deployment | `usr/lib/modules/7.3.0/{vmlinuz,initramfs.img}` ✅ |
| harness user | appendable `/etc/passwd`, `/bin/bash` | `etc/passwd` (system users only), `usr/bin/bash` ✅ |
| harness SSH | `sshd`, `sshd.service`, `scp`, `sftp-server` | ✅ (unit runs `ssh-keygen -A` itself) |
| harness admin | `sudo` | `usr/bin/sudo` + `etc/sudoers` ✅ |
| session | GDM, gnome-shell, Mutter, GJS | ✅ `etc/systemd/system/display-manager.service` → `gdm.service` |
| test stack install | `python3` + `ensurepip` | Python 3.14 with bundled pip wheel ✅ (no system pip) |
| AT-SPI | PyGObject, pyatspi, `at-spi-bus-launcher` | ✅ |
| virtual input | `uinput` module | `uinput.ko.zst` + `modules-load.d/uinput.conf` ✅ |
| virtual input | **`gnome-ponytail-daemon`** | **absent** ❌ |
| extensions | `gnome-extensions`, `gdbus` | ✅ |

Not verifiable without a boot, so still open: whether GNOME OS's first-boot
`gnome-initial-setup` (`usr/libexec/gnome-initial-setup` is present) interferes with GDM
autologin of the injected `bluefin-test` user, and whether `bootc install to-disk` completes on
this image with `--bootloader systemd`. Record both from the first lab run's `vm-serial.log`.

There is no package manager (no `dnf`/`rpm`); missing tooling must arrive in a test overlay or
sysext, recorded separately from the base digest.

## Pre-boot preflight (`scripts/guest_preflight.py`)

For `suite: extensions` the action runs the preflight over the mounted ostree deployment **before
the VM boots**. It writes `results/guest-provenance.json` and fails the job as a provisioning
error when any prerequisite above is missing (or the guest has no `os-release`). Today it fails
stock GNOME OS on exactly one item, `gnome-ponytail-daemon` — that is the correct, named failure
in place of a qecore error ten minutes later. It records `is_gnome_os` from `os-release`
`ID` but does not reject other images, so a Bluefin/Dakota extensions run stays possible and is
never labelled GNOME OS. The final path component is checked with `lexists` and never resolved,
and hits under a parent directory that resolves outside the guest tree are discarded, so
absolute guest symlinks are not followed onto the host.
