# developer test suite

Bluefin developer tooling — Ptyxis terminal, Podman, and Homebrew.

## Run via GitHub Action

```yaml
uses: projectbluefin/testsuite/.github/workflows/e2e.yml@v1
with:
  image: ghcr.io/ublue-os/bluefin:latest
  suites: developer
```

## Related skills

- Skill router: `docs/SKILL.md`
- `test-authoring/gnome/SKILL.md`
- `test-authoring/behave/SKILL.md`
