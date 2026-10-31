@software_suite
Feature: Bazaar installs and removes an app through its UI
  A real Flathub transaction driven through Bazaar 0.9.10: search, the app's
  page, Install, then Remove on the same page. Bazaar prefers system entries
  (bz_entry_calc_usefulness) and Flathub is a system remote, so it installs
  through libflatpak's system helper and polkit decides whether a prompt
  appears. Decoder is small (4.8 MB), verified, free software (no high-risk
  dialog) and runs on org.gnome.Platform//51, Bazaar's own runtime.
  Images without Bazaar skip through the _has_bazaar() guard.

  @retry @software @bazaar_ui @transaction
  Scenario: An app found by search installs and uninstalls from its Bazaar page
    * Flatpak app "com.belmoussaoui.Decoder" is absent and unused, and removed again when the scenario ends
    * Launch Bazaar
    * Bazaar main window is accessible
    * Bazaar main content is loaded
    * polkit lets Bazaar install and remove system Flatpaks without a prompt
    * Bazaar tab "Search" is accessible
    * Activate Bazaar tab "Search"
    * Bazaar view "Search" is loaded
    * Focus the Bazaar window
    * Type text: "decoder" with uinput
    * Bazaar search field shows "decoder"
    * Bazaar search results include "Decoder"
    * Open Bazaar search result "Decoder" with the keyboard
    * Install "com.belmoussaoui.Decoder" from the Bazaar page of "Decoder"
    * Run SSH command: "flatpak info --system com.belmoussaoui.Decoder"
    * SSH command return code is "0"
    * Flatpak app "com.belmoussaoui.Decoder" is from remote "flathub"
    * Remove "com.belmoussaoui.Decoder" from the Bazaar page of "Decoder"
    * Flatpak app "com.belmoussaoui.Decoder" is not installed
    * No coredump entries exist on the VM for "bazaar"
