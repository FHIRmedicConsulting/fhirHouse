#!/usr/bin/env bash
# bootstrap-fork.sh — establish fhirHouse as a proper fork of fhirEngine.
#
# Run this ON YOUR HOST (e.g. from Claude Code), NOT in the sandbox. The sandbox
# mount cannot manage git lock files, which is why the scaffolder placed plain
# files here instead of a live repo.
#
# This preserves the additive fhirHouse files already in this directory and
# layers them over fhirEngine's full history via the `upstream` remote, so future
# `git merge upstream/main` pulls fhirEngine improvements in.

set -euo pipefail

UPSTREAM="https://github.com/FHIRmedicConsulting/fhirEngine.git"

# 0. Clean any partial state left by the scaffolder (sandbox couldn't delete these).
rm -f _mounttest.txt 2>/dev/null || true
rm -rf .git 2>/dev/null || true

# 1. Init and pull fhirEngine's history via `upstream`.
git init -q
git remote add upstream "$UPSTREAM"
git fetch --quiet upstream

# `checkout -b main upstream/main` writes fhirEngine's tree into the working dir;
# the additive fhirHouse files (FH-*, warehouse-gov/, dbt/, ...) don't exist in
# upstream, so they are left untracked and preserved.
git checkout -q -b main upstream/main

# 2. Stage the fhirHouse additive layer + commit.
git add -A
git commit -q -m "fhirHouse: governance/DQ/MDM/lineage scaffold over fhirEngine fork (medallion build-out)"

cat <<'DONE'

fhirHouse fork established.
  upstream -> https://github.com/FHIRmedicConsulting/fhirEngine.git
  pull future fhirEngine improvements:  git fetch upstream && git merge upstream/main

Next: create your GitHub repo and set it as origin, e.g.
  gh repo create <you>/fhirHouse --private --source=. --remote=origin --push
DONE
