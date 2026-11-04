# software test suite

Bazaar (Bluefin software center) and Flatpak coverage. Upstream GNOME Software
scenarios in `flatpak.feature` are `@future` (#847).

## Run via GitHub Action

```yaml
uses: projectbluefin/testsuite/.github/workflows/e2e.yml@v1
with:
  image: ghcr.io/projectbluefin/bluefin:testing
  suites: software
```

## Related skills

- Skill router: `docs/SKILL.md`
- `test-authoring/behave/SKILL.md`
- `test-authoring/gnome/SKILL.md`
