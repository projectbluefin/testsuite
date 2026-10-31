---
name: common-rationalizations
description: "Deep dive: Common Rationalizations"
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Common Rationalizations

## Common Rationalizations

- "The cache can target the runner user's podman storage."  
  It cannot here — the pulls run under `sudo`, so cache the root store or the pull will still miss.
- "A floating `uses:` tag is fine for a speedup-only change."  
  It is not; external actions in this repo must stay SHA-pinned.
- "We can call `ublue-os/remove-unwanted-software` directly or inline a cleanup for speed."  
  Disk cleanup goes through the org's `projectbluefin/actions/bootc-build/setup-runner` (v9 direct use hit `No space left on device` in E2E and manual software runs). Inline cleanup is only worthwhile if that action is the measured bottleneck — do not change this without profiling.
