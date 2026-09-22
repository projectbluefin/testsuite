@accessibility @gsettings @vanilla_gnome
Feature: GNOME 51 accessibility gsettings round-trips
  GNOME 51 added two new settings to the
  ``org.gnome.desktop.a11y.interface`` schema that pre-51 images do not ship:
  ``reduced-motion`` and ``keyboard-focus-visible-timeout``. These scenarios
  write each key, read it back, restore the shipped default, and confirm the
  toggle raised no accessibility journal errors.

  The scenarios are gated with ``@requires_gnome_51``; ``environment.py`` probes
  the running GNOME Shell version and skips them cleanly on GNOME <= 50 images
  (runtime version probe, not a non-runnable tag).

  @requires_gnome_51 @reduced_motion
  Scenario: Reduced-motion setting round-trips through gsettings
    # org.gnome.desktop.a11y.interface reduced-motion (enum: no-preference,
    # reduce; default no-preference) is new in GNOME 51.
    * Run and save command output: "gsettings set org.gnome.desktop.a11y.interface reduced-motion reduce"
    * Return code of last command output "is" "0"
    * Run and save command output: "gsettings get org.gnome.desktop.a11y.interface reduced-motion"
    * Last command output stripped "is" "reduce"
    * Run and save command output: "gsettings set org.gnome.desktop.a11y.interface reduced-motion no-preference"
    * Return code of last command output "is" "0"
    * Run and save command output: "journalctl -b --no-pager -p err -g 'at-spi|orca|accessibility' -q | grep -v '^--' | grep -v '^$' | wc -l"
    * Last command output stripped "is" "0"

  @requires_gnome_51 @focus_ring
  Scenario: Keyboard focus-visible timeout round-trips through gsettings
    # org.gnome.desktop.a11y.interface keyboard-focus-visible-timeout (int;
    # default -1) is new in GNOME 51. 0 means "forever", -1 means "use the
    # default toolkit value".
    * Run and save command output: "gsettings set org.gnome.desktop.a11y.interface keyboard-focus-visible-timeout 5"
    * Return code of last command output "is" "0"
    * Run and save command output: "gsettings get org.gnome.desktop.a11y.interface keyboard-focus-visible-timeout"
    * Last command output stripped "is" "5"
    * Run and save command output: "gsettings set org.gnome.desktop.a11y.interface keyboard-focus-visible-timeout -1"
    * Return code of last command output "is" "0"
    * Run and save command output: "journalctl -b --no-pager -p err -g 'at-spi|orca|accessibility' -q | grep -v '^--' | grep -v '^$' | wc -l"
    * Last command output stripped "is" "0"
