#!/bin/bash
# Compose the E2E test image: build a derived container layer FROM the image
# under test that adds the software the suites need, then push it to GHCR so
# the suite jobs boot the composed image instead of the raw one.
#
# Why: installing packages at runtime inside the VM (rpm-ostree install
# --apply-live) fails on images that lock runtime layering — bluefin-lts
# deliberately ships rpm-ostreed.conf with LockLayering=true
# (projectbluefin/bluefin-lts#492, PR #509). Composing the software as a
# container layer at build time works everywhere.
#
# Usage:
#   compose-e2e-image.sh <base-image-ref> <composed-image-ref>
#
# Environment variables:
#   E2E_OVERLAY_DIR — build context containing the overlay Containerfile
#                     (default: container/e2e-overlay relative to the repo root).
#   PODMAN          — podman binary/wrapper (default: sudo podman, matching how
#                     e2e.yml pulls into the root image store).
#
# The caller is responsible for registry login (podman login ghcr.io) before
# invoking this script; in CI the reusable workflow does this with GITHUB_TOKEN.
#
# Outputs: pushes <composed-image-ref> and prints it on the last stdout line.

set -euo pipefail

log() { echo "[compose-e2e-image] $*"; }

if [[ $# -ne 2 ]]; then
  log "usage: $0 <base-image-ref> <composed-image-ref>" >&2
  exit 2
fi

BASE_IMAGE="$1"
COMPOSED_REF="$2"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OVERLAY_DIR="${E2E_OVERLAY_DIR:-${REPO_ROOT}/container/e2e-overlay}"
PODMAN="${PODMAN:-sudo podman}"

if [[ ! -f "${OVERLAY_DIR}/Containerfile" ]]; then
  log "overlay Containerfile not found in ${OVERLAY_DIR}" >&2
  exit 1
fi

log "base image:     ${BASE_IMAGE}"
log "composed image: ${COMPOSED_REF}"

${PODMAN} build \
  --build-arg BASE_IMAGE="${BASE_IMAGE}" \
  -f "${OVERLAY_DIR}/Containerfile" \
  -t "${COMPOSED_REF}" \
  "${OVERLAY_DIR}"

log "pushing ${COMPOSED_REF}"
DIGEST_FILE="$(mktemp)"
${PODMAN} push --digestfile="${DIGEST_FILE}" "${COMPOSED_REF}"
DIGEST="$(cat "${DIGEST_FILE}")"
rm -f "${DIGEST_FILE}"

if [[ "${DIGEST}" != sha256:* ]]; then
  log "push produced invalid or missing digest: '${DIGEST}'" >&2
  exit 1
fi
PINNED_REF="${COMPOSED_REF%:*}@${DIGEST}"
log "compose complete (digest: ${DIGEST})"
echo "${COMPOSED_REF}"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "digest=${DIGEST}" >> "${GITHUB_OUTPUT}"
  echo "pinned_image=${PINNED_REF}" >> "${GITHUB_OUTPUT}"
fi
