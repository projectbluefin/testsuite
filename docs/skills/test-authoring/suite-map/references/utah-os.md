---
name: utah-os
description: Utah-only common-suite scenarios (@utah_only), their shipping evidence, and the known report-routing defect.
---

# Utah OS coverage

`tests/common/features/utah_os.feature` is feature-level `@common @utah_only`.
`tests/common/features/environment.py` skips `@utah_only` unless the image
under test (`BASE_IMAGE`, then `IMAGE`) has `utah` in its image name.

Evidence: projectbluefin/utah `527c5aff` and
`ghcr.io/projectbluefin/utah@sha256:a0baa947…`.

| Scenario | Shipping source |
|---|---|
| os-release identity | `scripts/configure-branding.sh` |
| image-info name and flavor | `scripts/configure-branding.sh`, `config/flavors.json` |
| zram swap | `zram-generator-defaults` (`/usr/lib/systemd/zram-generator.conf`) |
| Lid switch policy | `scripts/configure-services.sh` (logind.conf) |
| authselect features | `scripts/configure-services.sh` |
| resolved `PrivateTmp=no` | `scripts/configure-services.sh` |
| tuna-os remote | `/etc/flatpak/remotes.d/tuna-os.flatpakrepo` |
| Bazaar and Ghostty preinstall | `/usr/share/flatpak/preinstall.d/*.preinstall` |
| `ujust report` routing | `60-custom.just`, `scripts/image-repo.sh` |
| CountMe timer, burst limit, opt-out | common CountMe units plus `10-utah-burst-tolerance.conf`; opt-out mirrors `iso/scripts/verify-countme-runtime.sh` and never runs the client. The e2e harness writes `/etc/projectbluefin/countme/disabled`, so the shipped default is read from `/usr/etc` and the opt-out probe reuses a pre-existing marker, restoring the prior state either way |
| Ghostty user hook | `user-setup.hooks.d/30-ghostty.sh` |

## Known defect

`ujust report` sets `UBLUE_IMAGE_REPO_BIN=/usr/local/libexec/utah-image-repo`.
On bootc, `/usr/local` is `/var/usrlocal`, so the shim is not in the image
(`sha256:a0baa947` has no `/usr/local/libexec`). The routing scenario is
expected to fail until Utah installs the shim under `/usr`.

Out of scope: NVIDIA, OGC kernel and other flavor hardware runtime.
