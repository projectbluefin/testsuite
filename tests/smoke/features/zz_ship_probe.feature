@smoke_suite
Feature: Ship probe (throwaway spike, not for merge)
  Records what the booted image really ships (packages, binaries, desktop
  files, Flatpaks, extensions, settings, units, tooling) as ship-probe.txt in
  the results artifact. Read-only. Carries no image-family tag (@bluefin,
  @dakota_only, @dakota_family, @bluefin_classic) and no app-availability
  tag, so it runs on both Dakota and Utah. The file name sorts last, so it
  runs after every other smoke feature in its shard.

  @ship_probe
  Scenario: Record what the booted image ships
    * the ship probe records what the booted image ships
