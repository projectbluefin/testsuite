@security @cosign @preflight
Feature: Container image signature verification
  Validates that projectbluefin images are correctly signed by the upstream build
  system (projectbluefin GitHub Actions).
  Runner: plain SSH or local (cosign CLI needed).

  # This does NOT replicate signing infrastructure.
  # The build systems sign; we only verify the signatures are sound.
  # See QA-REVIEW.md Epic E03 for full design.

  # ── projectbluefin images ──────────────────────────────────────────────────

  @cosign @projectbluefin @pb_dakota_latest
  Scenario: projectbluefin Dakota latest image has valid cosign signature
    * Cosign certificate issuer is "https://token.actions.githubusercontent.com" and identity pattern is "https://github.com/projectbluefin/.*"
    * Verify cosign signature for "ghcr.io/projectbluefin/dakota:latest"
    * Signature OIDC issuer is "https://token.actions.githubusercontent.com"
    * Signature identity matches "https://github.com/projectbluefin/.*"

  @cosign @negative
  Scenario: Unsigned image fails verification gracefully
    * Verify cosign signature for "docker.io/library/busybox:latest" expecting failure
    * Verification error message is clear and actionable
