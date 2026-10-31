@smoke_suite @bluefin
Feature: OOTB Flatpak sandbox permission auditing
  Pin the effective filesystem grants (Flathub metadata plus image overrides
  from `flatpak info --system --show-permissions`) of the OOTB Flatpaks so any
  widening or narrowing of host filesystem access fails with the diff.

  # Active audits cover the Flatpaks the Bluefin/Utah GUI lanes preload from
  # flatpak-app-list.txt (flatpak-preinstall.service is masked in CI). Expected
  # sets were read from installed Flathub builds on 2026-10-31 (Firefox 159.0,
  # Bazaar 0.9.10, Papers 51.1, Loupe 51.rc, Showtime 50.0) plus the image
  # override /usr/share/ublue-os/flatpak-overrides/io.github.kolunmi.Bazaar
  # (filesystems=host-etc), linked into /var/lib/flatpak/overrides by
  # /usr/lib/tmpfiles.d/bazaar-flatpak.conf on Bluefin and Utah.
  # @ci_seeded_flatpak skips them on refs e2e.yml does not preload (bazzite,
  # common); see ci_seeds_flatpaks in environment.py.
  # A Flathub permission change fails here on purpose: review it, then update.

  @permissions @ci_seeded_flatpak
  Scenario: Firefox Flatpak filesystem grants match the audited set
    * Flatpak "org.mozilla.firefox" grants exactly the filesystems "xdg-config/gtk-3.0:ro;xdg-download;/run/.heim_org.h5l.kcm-socket;/run/udev:ro;xdg-run/speech-dispatcher:ro"

  @permissions @ci_seeded_flatpak
  Scenario: Bazaar Flatpak filesystem grants match the audited set including the image host-etc override
    * Flatpak "io.github.kolunmi.Bazaar" grants exactly the filesystems "/var/tmp;/var/lib/flatpak;~/.var/app;xdg-data/flatpak;host-etc"

  @permissions @ci_seeded_flatpak
  Scenario: Papers Flatpak filesystem grants are read-only home and removable media
    * Flatpak "org.gnome.Papers" grants exactly the filesystems "home:ro;/media:ro;xdg-run/gvfsd;/run/media:ro;xdg-run/gvfs"

  # Loupe's upstream Flathub manifest grants full read-write `host`; pinned so
  # the broad grant is visible and any change is reviewed.
  @permissions @ci_seeded_flatpak
  Scenario: Loupe Flatpak filesystem grants match the audited set
    * Flatpak "org.gnome.Loupe" grants exactly the filesystems "xdg-run/gvfsd;host;xdg-run/gvfs"

  @permissions @ci_seeded_flatpak
  Scenario: Showtime Flatpak has no filesystem grants
    * Flatpak "org.gnome.Showtime" grants no filesystem access

  # Pending: the remaining system-flatpaks.Brewfile apps (common e33665e2
  # system_files/bluefin/usr/share/ublue-os/homebrew/system-flatpaks.Brewfile)
  # are not preloaded by CI, and flatpak-preinstall.service stays masked.
  # Blocked until flatpak-app-list.txt seeds them (CI-interface change,
  # human sign-off required).

  @permissions @pending
  Scenario: Calculator Flatpak has no filesystem grants
    * Flatpak "org.gnome.Calculator" grants no filesystem access

  @permissions @pending
  Scenario: be.alexandervanhee.gradia is installed system-wide
    * Flatpak "be.alexandervanhee.gradia" is installed system-wide

  @permissions @pending
  Scenario: com.github.PintaProject.Pinta is installed system-wide
    * Flatpak "com.github.PintaProject.Pinta" is installed system-wide

  @permissions @pending
  Scenario: com.github.tchx84.Flatseal is installed system-wide
    * Flatpak "com.github.tchx84.Flatseal" is installed system-wide

  @permissions @pending
  Scenario: com.mattjakeman.ExtensionManager is installed system-wide
    * Flatpak "com.mattjakeman.ExtensionManager" is installed system-wide

  @permissions @pending
  Scenario: com.ranfdev.DistroShelf is installed system-wide
    * Flatpak "com.ranfdev.DistroShelf" is installed system-wide

  @permissions @pending
  Scenario: io.github.flattool.Ignition is installed system-wide
    * Flatpak "io.github.flattool.Ignition" is installed system-wide

  @permissions @pending
  Scenario: io.gitlab.adhami3310.Impression is installed system-wide
    * Flatpak "io.gitlab.adhami3310.Impression" is installed system-wide

  @permissions @pending
  Scenario: io.missioncenter.MissionCenter is installed system-wide
    * Flatpak "io.missioncenter.MissionCenter" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.Calculator is installed system-wide
    * Flatpak "org.gnome.Calculator" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.Calendar is installed system-wide
    * Flatpak "org.gnome.Calendar" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.Characters is installed system-wide
    * Flatpak "org.gnome.Characters" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.Connections is installed system-wide
    * Flatpak "org.gnome.Connections" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.Contacts is installed system-wide
    * Flatpak "org.gnome.Contacts" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.Decibels is installed system-wide
    * Flatpak "org.gnome.Decibels" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.DejaDup is installed system-wide
    * Flatpak "org.gnome.DejaDup" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.FileRoller is installed system-wide
    * Flatpak "org.gnome.FileRoller" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.Firmware is installed system-wide
    * Flatpak "org.gnome.Firmware" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.Logs is installed system-wide
    * Flatpak "org.gnome.Logs" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.Maps is installed system-wide
    * Flatpak "org.gnome.Maps" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.NautilusPreviewer is installed system-wide
    * Flatpak "org.gnome.NautilusPreviewer" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.SimpleScan is installed system-wide
    * Flatpak "org.gnome.SimpleScan" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.Snapshot is installed system-wide
    * Flatpak "org.gnome.Snapshot" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.TextEditor is installed system-wide
    * Flatpak "org.gnome.TextEditor" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.Weather is installed system-wide
    * Flatpak "org.gnome.Weather" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.baobab is installed system-wide
    * Flatpak "org.gnome.baobab" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.clocks is installed system-wide
    * Flatpak "org.gnome.clocks" is installed system-wide

  @permissions @pending
  Scenario: org.gnome.font-viewer is installed system-wide
    * Flatpak "org.gnome.font-viewer" is installed system-wide

  @permissions @pending
  Scenario: org.mozilla.thunderbird is installed system-wide
    * Flatpak "org.mozilla.thunderbird" is installed system-wide

  @permissions @pending
  Scenario: page.tesk.Refine is installed system-wide
    * Flatpak "page.tesk.Refine" is installed system-wide
