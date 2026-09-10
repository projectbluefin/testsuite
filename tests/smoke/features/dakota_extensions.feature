@smoke_suite @dakota_only
Feature: Dakota GNOME Shell extension presence and configuration
  Validates that all extensions shipped by Dakota in projectbluefin/dakota
  (elements/bluefin/gnome-shell-extensions.bst) are present and installed,
  that default desktop extensions are in ENABLED state, that personal integrations
  are present and valid, and that dconf schema overrides match the shipped specification.

  # ---------------------------------------------------------------------------
  # Default-enabled extensions (from disable-ext-validator.bst)
  # ---------------------------------------------------------------------------

  @dakota_only @extensions
  Scenario: AppIndicator support extension is enabled on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "appindicatorsupport@rgcjonas.gmail.com" is enabled

  @dakota_only @extensions
  Scenario: Bazaar Integration extension is enabled on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "bazaar-integration@kolunmi.github.io" is enabled

  @dakota_only @extensions
  Scenario: Blur My Shell extension is enabled on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "blur-my-shell@aunetx" is enabled

  @dakota_only @extensions
  Scenario: BudsLink Companion extension is enabled on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "BudsLink-Companion@maniacx.github.com" is enabled
    * Dconf path "/org/gnome/shell/extensions/BudsLink-Companion/level-indicator-color" has value "0"

  @dakota_only @extensions
  Scenario: Caffeine extension is enabled on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "caffeine@patapon.info" is enabled

  @dakota_only @extensions
  Scenario: Custom Command Menu extension is enabled on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "custom-command-list@storageb.github.com" is enabled
    * Dconf path "/org/gnome/shell/extensions/custom-command-list/menuoptions-setting" has value "2"
    * Dconf path "/org/gnome/shell/extensions/custom-command-list/menuicon-setting" has value "'ublue-logo-symbolic'"

  @dakota_only @extensions
  Scenario: Dash to Dock extension is enabled on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "dash-to-dock@micxgx.gmail.com" is enabled

  @dakota_only @extensions
  Scenario: Fuzzy Application Search extension is enabled on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "fuzzy-application-search@mkhl.codeberg.page" is enabled

  @dakota_only @extensions
  Scenario: Gradia Capture Integration extension is enabled on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "gradia-integration@alexandervanhee.github.io" is enabled

  @dakota_only @extensions
  Scenario: GSConnect extension is enabled on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "gsconnect@andyholmes.github.io" is enabled

  @dakota_only @extensions
  Scenario: Tiling Shell extension is enabled on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "tilingshell@ferrarodomenico.com" is enabled
    * Dconf path "/org/gnome/shell/extensions/tilingshell/show-indicator" has value "false"

  # ---------------------------------------------------------------------------
  # Shipped personal & hardware integration extensions (installed in system)
  # ---------------------------------------------------------------------------

  @dakota_only @extensions
  Scenario: Copyous clipboard manager is installed on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "copyous@boerdereinar.dev" is installed

  @dakota_only @extensions
  Scenario: Power status color extension is installed on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "power-status-color@projectbluefin.io" is installed

  @dakota_only @extensions
  Scenario: Quick Settings Audio Panel extension is installed on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "quick-settings-audio-panel@rayzeq.github.io" is installed

  @dakota_only @extensions
  Scenario: Quick Settings audio device hider is installed on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "quicksettings-audio-devices-hider@marcinjahn.com" is installed

  @dakota_only @extensions
  Scenario: Quick Settings audio device renamer is installed on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "quicksettings-audio-devices-renamer@marcinjahn.com" is installed

  @dakota_only @extensions
  Scenario: Syncthing Toggle extension is installed and configured on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "syncthing-toggle@rehhouari.github.com" is installed
    * Dconf path "/org/gnome/shell/extensions/syncthing-toggle/start-stop-only" has value "true"

  @dakota_only @extensions
  Scenario: Tailscale Quick Settings extension is installed on Dakota
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "tailscale-gnome-qs@tailscale-qs.github.io" is installed
