#!/usr/bin/env bash
set -euo pipefail

# Compare the checked-out PR or merge-group commit to its event base.
changed=$(git diff --name-only --no-renames "$1" HEAD --)
runner=false
kde=false
while IFS= read -r path; do
  case "$path" in
    container/Containerfile.runner|.github/workflows/build-runner.yml) runner=true ;;
    container/Containerfile.kde-runner|container/requirements.kde-runner.txt|.github/workflows/build-kde-runner.yml) kde=true ;;
  esac
done <<< "$changed"
printf 'runner=%s\nkde=%s\n' "$runner" "$kde"
