@software_suite
Feature: Bazaar GUI deep navigation
  Validates Bazaar search and category navigation on Bluefin images.
  Complements bazaar_ui.feature (launch + tab visibility) by exercising
  the Curated tab and a typed search that must show a matching result.
  Scenarios skip automatically on images where Bazaar is absent via the
  existing _skip_if_no_atspi guard and the _has_bazaar() runtime check.

  GNOME 50 AT-SPI note: the Search tab is a toggle button in GNOME 50 but
  a page tab in GNOME 46/48. Both roles are covered by BAZAAR_TAB_ROLES in
  the software steps module, so no per-scenario workaround is needed.

  Background:
    * Launch Bazaar
    * Bazaar main window is accessible
    * Bazaar main content is loaded

  @retry @software @bazaar_ui @navigation
  Scenario: Curated tab is accessible and loads content
    * Bazaar tab "Curated" is accessible
    * Activate Bazaar tab "Curated"
    * Bazaar view "Curated" is loaded

  # Bazaar's window turns typed characters into a search (type-to-search),
  # so the query lands in the search field once the window has focus.
  # Lower case on purpose: python-uinput maps only unshifted characters.
  @retry @software @bazaar_ui @navigation @search
  Scenario: Search tab finds an app by its typed name
    * Bazaar tab "Search" is accessible
    * Activate Bazaar tab "Search"
    * Bazaar view "Search" is loaded
    * Focus the Bazaar window
    * Bazaar window has keyboard focus
    * Type text: "flatseal" with uinput
    * Bazaar search field shows "flatseal"
    * Bazaar search results include "Flatseal"

  @retry @software @bazaar_ui @navigation
  Scenario: Navigation between Explore and Library is stateless
    # Switch Explore → Library → Explore to confirm tab state resets cleanly.
    * Bazaar tab "Explore" is accessible
    * Activate Bazaar tab "Explore"
    * Bazaar view "Explore" is loaded
    * Bazaar tab "Library" is accessible
    * Activate Bazaar tab "Library"
    * Bazaar view "Library" is loaded
    * Bazaar tab "Explore" is accessible
    * Activate Bazaar tab "Explore"
    * Bazaar view "Explore" is loaded

  @retry @software @bazaar_ui @navigation
  Scenario: Navigation between all four tabs completes without crash
    # Walk Curated → Explore → Library → Search in order; assert Bazaar still
    # running and no coredump generated (regression guard for AT-SPI crashes).
    * Activate Bazaar tab "Curated"
    * Bazaar view "Curated" is loaded
    * Activate Bazaar tab "Explore"
    * Bazaar view "Explore" is loaded
    * Activate Bazaar tab "Library"
    * Bazaar view "Library" is loaded
    * Activate Bazaar tab "Search"
    * Bazaar view "Search" is loaded
    * Bazaar main window is accessible
    * No coredump entries exist on the VM for "bazaar"

  @software @bazaar_ui @close
  Scenario: Bazaar closes cleanly after deep navigation
    * Activate Bazaar tab "Explore"
    * Bazaar view "Explore" is loaded
    * Activate Bazaar tab "Library"
    * Bazaar view "Library" is loaded
    * Close Bazaar via shortcut
    * Bazaar is no longer running
    * No coredump entries exist on the VM for "bazaar"
