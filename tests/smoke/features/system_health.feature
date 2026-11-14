@smoke_suite
Feature: System health smoke checks
  Validates the booted image is healthy, identifiable as Bluefin, and has
  enough free root filesystem space for normal operation.

  # geoclue.service is VM-only and ignored in the step.
  # quarantine: projectbluefin/dakota#1875 nfs-idmapd and rpc-statd fail at boot on dakota:testing
  @health @systemd @sla_10s @quarantine
  Scenario: No failed systemd units at boot
    * No failed systemd units at boot

  @health @journal @sla_10s
  Scenario: No critical journal errors at boot
    * No critical kernel errors in journal

  @health @bluefin
  Scenario: Bluefin image identity is present in /etc/os-release
    * Bluefin image identity is present in os-release

  @health @bluefin
  Scenario: bootc status shows a known image reference
    * bootc status shows a valid image reference

  @health @storage
  Scenario: Writable system storage has more than 15 percent free space
    * Writable system storage has at least "15" percent free space

  @health @network
  Scenario: External DNS resolves external hosts
    * External DNS resolves external hosts

  @system_health @ujust @sla_10s
  Scenario: ujust is available and lists at least one task
    * ujust is on PATH and returns exit 0
    * ujust --list prints at least one task

  # Pending: `ujust report --confirm` validation ships in a `just` template change
  # that is not yet in the images CI boots; needs an image rebuild first.
  @system_health @ujust @ujust_report @pending
  Scenario: ujust report confirm validation rejects invalid inputs
    * ujust is on PATH and returns exit 0
    * ujust report --confirm rejects non-integer issue number
    * ujust report --confirm without issue number prints error

  # Re-activated: quarantined in #521 for projectbluefin/dakota#841. That
  # regression was composefs stripping security.capability xattrs from a
  # multi-layer OCI image; newuidmap/newgidmap (shadow-utils %caps) carry the
  # signal for that class and must stay active so a recurrence is caught.
  #
  # ping was dropped from this check: Fedora's iputils ships /usr/bin/ping
  # without a file capability (plain 0755; only clockdiff/arping get
  # %caps(cap_net_raw=p)) and relies on net.ipv4.ping_group_range for
  # unprivileged ping instead. A cap_net_raw assertion can never pass on a
  # Fedora-based image, so it only produced a deterministic false failure
  # (projectbluefin/bluefin#989 smoke-b) rather than a real regression signal.
  @health @composefs @regression @sla_10s
  Scenario: composefs preserves file capabilities on newuidmap and newgidmap
    * newuidmap and newgidmap retain their security.capability xattrs

  @health @gdm @regression @sla_10s
  Scenario: System boots to display manager, not emergency console
    * gdm.service is active
    * graphical.target is active

  @health @tailscale @sla_10s
  Scenario: tailscale is installed and daemon is running
    * tailscale is installed and daemon is running

  @health @uupd @sla_10s
  Scenario: uupd auto-updater is installed and configured
    * uupd auto-updater is installed and configured

  @health @fastfetch @sla_10s
  Scenario: fastfetch is present and operational
    * fastfetch is present and operational
