@common @bluefin
Feature: Bluefin common ujust recipes
  Validates non-destructive, non-interactive ujust recipes over SSH.

  Background:
    * Bluefin VM is booted and reachable over SSH

  Scenario: ujust check-local-overrides exits cleanly on a fresh system
    * Run SSH command: "NO_COLOR=1 ujust check-local-overrides"
    * SSH command return code is "0"

  Scenario: ujust logs-this-boot prints the current boot journal
    * Run SSH command: "ujust logs-this-boot"
    * SSH command return code is "0"
    * SSH command output is not empty

  Scenario: ujust bios-info prints firmware metadata
    * Run SSH command: "ujust bios-info"
    * SSH command return code is "0"
    * SSH command output contains "Manufacturer"

  # ujust toggle-updates prompts interactively (gum choose) by default and
  # cannot be driven from an SSH step in that mode. The recipe
  # now honors a non-interactive ACTION argument (projectbluefin/common):
  # `ujust toggle-updates enable|disable|cancel` skips all prompts. The
  # @requires_toggle_action gate probes for that contract and skips on images
  # that have not shipped it yet. See
  # docs/skills/test-authoring/behave/references/ujust-noninteractive.md.
  @pending @requires_toggle_action
  Scenario: ujust toggle-updates enables and disables the update timer non-interactively
    # Flip the update timer through the recipe itself, assert the state
    # changed, then flip it back so the scenario is repeatable. Matches the
    # recipe's own timer detection (uupd.timer, falling back to
    # rpm-ostreed-automatic.timer) and asserts the recipe's confirmation
    # output so a broken recipe cannot pass by leaving the timer untouched.
    * Run SSH command: "if systemctl cat -- uupd.timer >/dev/null 2>&1; then TIMER=uupd.timer; else TIMER=rpm-ostreed-automatic.timer; fi; if systemctl is-enabled --quiet \"$TIMER\"; then before=enabled; else before=disabled; fi; if [ \"$before\" = enabled ]; then OUT=$(ujust toggle-updates disable); else OUT=$(ujust toggle-updates enable); fi; if systemctl is-enabled --quiet \"$TIMER\"; then mid=enabled; else mid=disabled; fi; if [ \"$before\" = enabled ]; then ujust toggle-updates enable >/dev/null; else ujust toggle-updates disable >/dev/null; fi; if systemctl is-enabled --quiet \"$TIMER\"; then restored=enabled; else restored=disabled; fi; printf '%s' \"$OUT\" | grep -q 'Updates have been' && [ \"$mid\" != \"$before\" ] && [ \"$restored\" = \"$before\" ]"
    * SSH command return code is "0"

  # Pending: glow is unavailable because brew-setup.service is masked in CI (#487).
  @pending
  Scenario: ujust changelogs renders release notes
    * Run SSH command: "command -v glow >/dev/null && ujust changelogs"
    * SSH command return code is "0"
    * SSH command output is not empty
