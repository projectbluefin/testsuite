---
name: startup-service-inventory
description: "Which units the fast e2e lane masks, why, and how the startup-qualification lane runs and judges the shipped first-boot ones."
metadata:
  type: reference
  audience: agents
  maturity: draft
---
# Startup-service inventory

The fast hosted lane in `.github/workflows/e2e.yml` masks units before first
boot, through `systemd.mask=` in `KERNEL_ARGS` and through `/dev/null`
symlinks in each deployment's `/etc/systemd/system/`. A green fast-lane run
therefore says nothing about those units. `startup_service_inventory.yaml`
(repo root) classifies every masked unit:

| Category | Meaning | Fast-lane result counts as qualification? |
|---|---|---|
| `startup_contract` | Shipped first-boot, update or health path that a profile enables | No. Needs a representative startup lane (#1025) |
| `vm_inapplicable` | Needs hardware or a radio hosted QEMU lacks | Not applicable |
| `ci_noise` | Shipped background service outside first boot, masked for speed | No, but not a startup gap |

`tests/unit/test_startup_service_inventory.py` fails when a unit is masked
without an entry, when an entry is no longer masked, or when an entry's
`mask_sites` disagree with the workflow. Changing a mask in `e2e.yml` means
updating the inventory in the same PR.

## Gotchas found while building the inventory

- The symlink loop appends `.service`, `.socket`, `.path` and `.timer` to every
  token. A bare token (`cups`) already masks `cups.socket` and `cups.path`;
  dotted tokens (`cups.path`, `avahi-daemon.socket`) only create bogus
  `*.path.service` names.
- `cups.browsed.service` is not a real unit. Fedora ships
  `cups-browsed.service`, which neither mask site touches.
- Bluefin and Bluefin LTS enable `podman-auto-update.timer` with
  `systemctl --global`, i.e. for user managers. Both mask sites act on the
  system manager, so the shipped user timer is probably still active. Observe
  the user unit before claiming it is covered or masked.
- The fast lane replaces `flatpak-preinstall.service` with a runner-cached
  sideload of `flatpak-app-list.txt`, and `brew-setup.service` with direct
  `brew install`/dnf installs. Those substitutes must not satisfy startup
  assertions.

## Startup-qualification lane

`.github/workflows/startup-qualification.yml` boots a fresh disk of one image
with every required `startup_contract` unit left as shipped. It runs on
`workflow_dispatch` (inputs `image`, `profile`, `negative_control`) and on PRs
that touch the lane's own files. It is not a release gate.

- `scripts/startup_lane.py plan --profile P` turns the inventory into the
  run: kernel masks (only `vm_inapplicable`, `ci_noise` and `deferred` units),
  system and user units to observe, paths they must produce, extra checks, and
  the longest deadline. The workflow has no hard-coded `systemd.mask=`; a unit
  test enforces that and bans substitute installs (`flatpak install`,
  `brew install`, autologin) in the workflow.
- `scripts/startup_lane_collect.sh` runs in the guest over SSH and prints
  `@@ section` blocks: `systemctl show` for the units, produced paths, the
  image's own `preinstall.d` files, `remotes.d` names, configured remotes,
  installed system Flatpaks, and tmpfiles.d permission-override links with the
  app's effective permissions. It only reads state.
- `startup_lane.py evaluate` judges that evidence. The workflow polls every
  20s until nothing is pending; each unit fails once its `deadline_s` (seconds
  after QEMU start) passes. Exit 0 pass, 1 fail, 3 still pending.
- The `broken` matrix job adds `ExecStartPre=/bin/false` to
  `NetworkManager-wait-online.service` (required on every profile) and passes
  only if the run goes red for that unit (`--expect-failure`).

Each `startup_contract` entry carries a `startup_lane` block (`scope`,
`expect`, `deadline_s`, `produces`, `checks`, or `deferred`); the header of
`startup_service_inventory.yaml` defines the keys and
`tests/unit/test_startup_lane.py` validates them.

### Judging gotchas

- A oneshot whose `Condition*=` fails is reported by systemd as
  `inactive/dead result=success`. `brew-setup.service` does exactly that when
  `/usr/share/homebrew.tar.zst` is missing. The lane treats
  `ConditionResult=no` as a failure for a required unit, and
  `ConditionTimestampMonotonic=0` as "never started".
- `brew-setup.service` has no `RemainAfterExit`, so success is
  `inactive/dead`, not `active/exited`. `flatpak-preinstall.service` retries
  (`Restart=on-failure`); `auto-restart` is pending, not failed, until its
  deadline.
- `podman-auto-update.{service,timer}` are enabled per user (`--global`), so
  the lane reads them with `systemctl --user` in the SSH session. The service
  only has to be loadable and not failed; the timer starts it later.
- Flatpak state is judged only after `flatpak-preinstall.service` passes.
  `/etc/flatpak/preinstall.d` files override `/usr/share` ones with the same
  name, and `Install=false` drops a ref. Each declared ref must be installed
  system-wide, on the declared branch, from a configured remote.
- Permission overrides ship as tmpfiles.d `L` links into
  `/var/lib/flatpak/overrides/`. The link must resolve to the shipped file;
  for an installed app every override entry must show in
  `flatpak info --show-permissions` (`!token` must be absent).

### Harness differences from a real install

Test user `bluefin-test` (UID 1001, in `wheel`) with an SSH key, passwordless
sudo, sshd enabled, `selinux=0` (the enforcing lane is #1024), direct-kernel
boot, and SLIRP networking. No autologin, no session or dconf config, no
Flatpak, brew or package sideloads.

The image goes on disk with `bootc install to-disk`, not an installer, so the
lane sees no Flatpak remote an installer might add. That is deliberate: it
checks what the image alone declares.

`flatpak_remote: installer` on `flatpak-preinstall.service` records that
Bluefin's system Flathub remote comes from installers, not the image: the
`install-flatpaks.sh` that the projectbluefin/iso Justfile writes, and the
`install-system-flatpaks` ujust recipe, both run
`flatpak remote-add --system flathub`. When the image ships no `remotes.d` file
and no system remote is configured, the lane reports `flatpak remote` and each
uninstalled preinstall ref as `not qualified` instead of failing them. A
shipped or configured remote turns the full checks back on, so a missing ref,
wrong branch or unknown origin still fails.

## Still open (#1025)

- First hosted run (2026-10-28, `bluefin:stable`): every unit passed, but
  `io.github.kolunmi.Bazaar` was not installed. The image ships
  `bazaar.preinstall` and no `remotes.d` file, so with no system remote
  `flatpak preinstall` logs "Nothing to do" and exits 0. The inventory now
  records the remote as installer-provided (see above), so on this path
  Bluefin's preinstall refs are `not qualified`. Qualifying them needs either
  an image-shipped `remotes.d/flathub.flatpakrepo` (then drop
  `flatpak_remote: installer`) or an installer-path lane.
- Greenboot (`deferred`): automatic rollback needs a boot-counting bootloader
  path, which direct-kernel boot lacks (#706). The lane keeps both units
  masked and lists them as `not qualified`.
- Re-enabling the pending system-Flatpak permission and brew scenarios needs
  runtime evidence from this lane first; record each blocker individually.
- User-session first-login paths (`ublue-user-setup`, `brew-preinstall`,
  Brewfile Flatpaks) need a logged-in session and belong with #1026.
- Making the lane a consumer or promotion requirement is a release-policy
  decision (#1021, #1022).
