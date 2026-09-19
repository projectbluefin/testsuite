# Security policy

## Reporting

Report security vulnerabilities through [GitHub Private Vulnerability Reporting](https://github.com/projectbluefin/testsuite/security/advisories/new). Do not disclose an unpatched vulnerability in a public issue.

Include:

- vulnerability description and impact
- reproduction steps or proof of concept
- affected workflow, test suite, or dashboard component
- suggested mitigation, if available

## Response

The maintainers acknowledge reports within 48 hours and aim to assess them
within 7 days. Fix and disclosure timing depends on severity and coordination
with affected consumer repositories.

## Scope

This policy covers the reusable E2E workflow (`e2e.yml`), the QEMU/SSH test
harness, cosign image verification, GHCR artifact publishing, and the
QA dashboard pipeline in this repository.

Report vulnerabilities in third-party actions, test dependencies, or the
images under test to their respective upstream projects unless the issue is
introduced by this repository's integration.

## Safe handling

Do not commit credentials, private keys, tokens, or exploit payloads. Preserve
signature verification, minimal workflow permissions, and artifact-integrity
checks when investigating or fixing a security issue.
