@smoke_suite
Feature: Bluefin GNOME extension presence
  Validates that all extensions enabled by default in Bluefin are loaded
  and in ENABLED state. A non-1 state means the extension crashed or was
  disabled — which breaks the Bluefin UX.

  # Enabled by default: Bluefin bundled GNOME extensions

  @extensions
  Scenario: AppIndicator support extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "appindicatorsupport@rgcjonas.gmail.com" is enabled

  @extensions
  Scenario: Bazaar Integration extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "bazaar-integration@kolunmi.github.io" is enabled

  @extensions
  Scenario: Blur My Shell extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "blur-my-shell@aunetx" is enabled

  @extensions
  Scenario: Caffeine extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "caffeine@patapon.info" is enabled

  @extensions
  Scenario: Dash to Dock extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "dash-to-dock@micxgx.gmail.com" is enabled

  @extensions
  Scenario: Gradia Integration extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "gradia-integration@alexandervanhee.github.io" is enabled

  @extensions
  Scenario: GSConnect extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "gsconnect@andyholmes.github.io" is enabled

  @extensions
  Scenario: Custom Command List extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "custom-command-list@storageb.github.com" is enabled

