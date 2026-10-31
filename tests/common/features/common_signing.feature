@common @bluefin
Feature: Bluefin common image signing and security invariants
  Validates signing keys, flatpak config, and security-critical files over SSH.

  Background:
    * Bluefin VM is booted and reachable over SSH

  # common system_files/shared ships policy.json + both keys; bluefin
  # build_files/base/20-tests.sh hard-asserts the same hashes at build time.
  Scenario: Container signing policy exists for ublue-os images
    * Run SSH command: "jq -r '.transports.docker["ghcr.io/ublue-os"][0] | [.type, .keyPaths[]] | join(" ")' /etc/containers/policy.json"
    * SSH command output "is" "sigstoreSigned /usr/lib/pki/containers/ublue-os.pub /usr/lib/pki/containers/ublue-os-backup.pub"

  Scenario: ublue-os signing keys are present and match expected hashes
    * Run SSH command: "jq -r '.transports.docker["ghcr.io/ublue-os"][0].keyPaths[]' /etc/containers/policy.json | xargs sha256sum | cut -d' ' -f1 | paste -sd' '"
    * SSH command output "is" "af78ecfda6eb21c35195af3739341715e9cfc3f2f5911dd9c10b0670547bf6e8 b723467015ba562d40b4645c98c51c65d8254bb59444f6e9962debcfe2315da0"

  Scenario: Bazaar flatpak preinstall file is present
    * Run SSH command: "test -f /usr/share/flatpak/preinstall.d/bazaar.preinstall"
    * SSH command return code is "0"

  Scenario: Fedora flatpak repo unit is absent
    * Run SSH command: "test ! -f /usr/lib/systemd/system/flatpak-add-fedora-repos.service"
    * SSH command return code is "0"

  Scenario: ujust binary is installed
    * Run SSH command: "stat /usr/bin/ujust"
    * SSH command return code is "0"
