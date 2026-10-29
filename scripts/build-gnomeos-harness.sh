#!/usr/bin/env bash
# Resolve short-lived official images once, then build only from digest pins.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
OUTPUT=${1:-results}
mkdir -p "$OUTPUT"
CONTEXT=$(mktemp -d)
trap 'rm -rf "$CONTEXT"' EXIT
REGISTRY=quay.io/gnome_infrastructure/gnome-build-meta
BASE_DIGEST=$(skopeo inspect --override-arch amd64 "docker://${REGISTRY}:gnomeos-nightly" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Digest"])')
DEVEL_DIGEST=$(skopeo inspect --override-arch amd64 "docker://${REGISTRY}:gnomeos-devel-nightly" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Digest"])')
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
}, indent=2) + '\n')
PY
curl --fail --location --retry 3 \
  https://gitlab.gnome.org/ofourdan/gnome-ponytail-daemon/-/archive/0.0.11/gnome-ponytail-daemon-0.0.11.tar.gz \
  -o "$CONTEXT/ponytail.tar.gz"
echo "$PONYTAIL_SHA256  $CONTEXT/ponytail.tar.gz" | sha256sum -c -
cp "$REPO_ROOT/container/Containerfile.gnomeos-harness" "$CONTEXT/Containerfile"
podman build --arch amd64 --build-arg "GNOMEOS_BASE=$GNOMEOS_BASE" \
  --build-arg "GNOMEOS_DEVEL=$GNOMEOS_DEVEL" \
  --tag localhost/gnomeos-harness:canary "$CONTEXT"
podman image inspect localhost/gnomeos-harness:canary > "$OUTPUT/harness-image-inspect.json"
python3 - "$OUTPUT" <<'PY'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
path = out / 'harness-provenance.json'
data = json.loads(path.read_text())
data['harness_image_id'] = json.loads((out / 'harness-image-inspect.json').read_text())[0]['Id']
path.write_text(json.dumps(data, indent=2) + '\n')
PY
