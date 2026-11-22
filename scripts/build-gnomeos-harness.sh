#!/usr/bin/env bash
# Resolve short-lived official images once, then build only from digest pins.
# Digest overrides (GNOMEOS_BASE_DIGEST / GNOMEOS_DEVEL_DIGEST) let a scheduled
# rerun rebuild the harness from a pinned GNOME OS build instead of the current
# nightly -- see .github/workflows/extension-validation-scheduled.yml.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
OUTPUT=${1:-results}
mkdir -p "$OUTPUT"
CONTEXT=$(mktemp -d)
trap 'rm -rf "$CONTEXT"' EXIT
REGISTRY=quay.io/gnome_infrastructure/gnome-build-meta
if [[ -n "${GNOMEOS_BASE_DIGEST:-}" ]]; then
  BASE_DIGEST="${GNOMEOS_BASE_DIGEST}"
else
  BASE_DIGEST=$(skopeo inspect --override-arch amd64 "docker://${REGISTRY}:gnomeos-nightly" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Digest"])')
fi
if [[ -n "${GNOMEOS_DEVEL_DIGEST:-}" ]]; then
  DEVEL_DIGEST="${GNOMEOS_DEVEL_DIGEST}"
else
  DEVEL_DIGEST=$(skopeo inspect --override-arch amd64 "docker://${REGISTRY}:gnomeos-devel-nightly" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Digest"])')
fi
[[ "$BASE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ && "$DEVEL_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
export GNOMEOS_BASE="${REGISTRY}@${BASE_DIGEST}" GNOMEOS_DEVEL="${REGISTRY}@${DEVEL_DIGEST}"
export PONYTAIL_SHA256=9b18d267c55ec950beeea42d3291d2e77f8f7e351c31c6a48feb90dacb195fc5
# Write the attempted provenance even if download/build fails.
python3 - "$OUTPUT/harness-provenance.json" <<'PY'
import json, os, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    'base_image': os.environ['GNOMEOS_BASE'],
    'builder_image': os.environ['GNOMEOS_DEVEL'],
    'ponytail_version': '0.0.11',
    'ponytail_source_sha256': os.environ['PONYTAIL_SHA256'],
    'harness_image_id': None,
    'os_release': None,
    'shell_version': None,
}, indent=2) + '\n')
PY
curl --fail --location --retry 3 \
  https://gitlab.gnome.org/ofourdan/gnome-ponytail-daemon/-/archive/0.0.11/gnome-ponytail-daemon-0.0.11.tar.gz \
  -o "$CONTEXT/ponytail.tar.gz"
echo "$PONYTAIL_SHA256  $CONTEXT/ponytail.tar.gz" | sha256sum -c -
cp "$REPO_ROOT/container/Containerfile.gnomeos-harness" "$CONTEXT/Containerfile"
cp "$REPO_ROOT/scripts/configure_gnomeos_canary_shell.py" "$CONTEXT/"
cp "$REPO_ROOT/container/gnomeos-harness-identity.py" "$CONTEXT/"
podman build --arch amd64 --build-arg "GNOMEOS_BASE=$GNOMEOS_BASE" \
  --build-arg "GNOMEOS_DEVEL=$GNOMEOS_DEVEL" \
  --tag localhost/gnomeos-harness:canary "$CONTEXT"
podman image inspect localhost/gnomeos-harness:canary > "$OUTPUT/harness-image-inspect.json"
# Record the GNOME OS nightly release and shell version the extension is tested
# on, straight from the devel image the harness was built from.
OS_RELEASE=$(podman run --rm "$GNOMEOS_DEVEL" cat /usr/lib/os-release 2>/dev/null | sed -n 's/^VERSION="\(.*)"$/\1/p' | head -1)
SHELL_VERSION=$(podman run --rm "$GNOMEOS_DEVEL" gnome-shell --version 2>/dev/null | sed -n 's/^GNOME Shell \(.*\)/\1/p' | head -1)
export OS_RELEASE SHELL_VERSION
python3 - "$OUTPUT" <<'PY'
import json, os, sys
from pathlib import Path
out = Path(sys.argv[1])
path = out / 'harness-provenance.json'
data = json.loads(path.read_text())
data['harness_image_id'] = json.loads((out / 'harness-image-inspect.json').read_text())[0]['Id']
data['os_release'] = os.environ.get('OS_RELEASE') or data['os_release']
data['shell_version'] = os.environ.get('SHELL_VERSION') or data['shell_version']
data['base_digest'] = data['base_image'].split('@', 1)[1] if '@' in data['base_image'] else None
data['devel_digest'] = data['builder_image'].split('@', 1)[1] if '@' in data['builder_image'] else None
path.write_text(json.dumps(data, indent=2) + '\n')
PY
