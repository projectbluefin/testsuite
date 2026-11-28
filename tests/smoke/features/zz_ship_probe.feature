@smoke_suite
Feature: Ship probe (throwaway spike, not for merge)
  Records what the booted image really ships as ship-probe.txt in the results
  artifact. Read-only. It carries no image-family tag and no app tag, so it runs
  on both Dakota and Utah. The file name sorts last in its shard.

  @ship_probe
  Scenario: Record what the booted image ships
    * the ship probe records what the booted image ships
