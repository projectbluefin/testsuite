@common @bluefin
Feature: Bluefin common image signing and security invariants
  Validates signing keys, flatpak config, and security-critical files over SSH.

  Background:
    * Bluefin VM is booted and reachable over SSH

  # common system_files/shared ships policy.json + both keys; bluefin
  # build_files/base/20-tests.sh hard-asserts the same hashes at build time.
  Scenario: Container signing policy exists for ublue-os images
    * Run SSH command: "test -f /etc/containers/policy.json && jq -e '.transports.docker.\"ghcr.io/ublue-os\"' /etc/containers/policy.json"
    * SSH command return code is "0"
    * SSH command output is not empty

  Scenario: ublue-os signing keys are present and match expected hashes
    * Run SSH command: "key1=$(jq -r '.transports.docker.\"ghcr.io/ublue-os\"[0].keyPaths[0]' /etc/containers/policy.json); backup=$(jq -r '.transports.docker.\"ghcr.io/ublue-os\"[0].keyPaths[1]' /etc/containers/policy.json); test -f \"$key1\" && test -f \"$backup\" && [ \"$(sha256sum \"$key1\" | cut -d' ' -f1)\" = \"af78ecfda6eb21c35195af3739341715e9cfc3f2f5911dd9c10b0670547bf6e8\" ] && [ \"$(sha256sum \"$backup\" | cut -d' ' -f1)\" = \"b723467015ba562d40b4645c98c51c65d8254bb59444f6e9962debcfe2315da0\" ] && echo ok"
    * SSH command output "is" "ok"

  Scenario: Bazaar flatpak preinstall file is present
    * Run SSH command: "test -f /usr/share/flatpak/preinstall.d/bazaar.preinstall"
    * SSH command return code is "0"

  Scenario: Fedora flatpak repo unit is absent
    * Run SSH command: "test ! -f /usr/lib/systemd/system/flatpak-add-fedora-repos.service"
    * SSH command return code is "0"

  Scenario: ujust binary is installed
    * Run SSH command: "stat /usr/bin/ujust"
    * SSH command return code is "0"
