#!/usr/bin/env bash
# Ensure /data/specter-opt is at origin/main without losing runtime state.
#
# Why not `git clone` into an existing dir, or `git pull`?
#   - Schedules reuse their sandbox, so the repo often already exists
#     ("destination path already exists").
#   - Local commits in the reused clone make `git pull` abort with
#     "Need to specify how to reconcile divergent branches".
# fetch + reset --hard always lands on the remote tip and leaves UNTRACKED
# files (data/.credits.env, data/risk_state.json) in place.
#
# Falls back to a clean clone if the directory is present but not a repo.
set -euo pipefail

REPO="${1:-/data/specter-opt}"
REMOTE="${SPECTER_GIT_REMOTE:-https://github.com/specter165/specter-opt.git}"
BRANCH="${SPECTER_GIT_BRANCH:-main}"

if [ -d "$REPO/.git" ]; then
  git -C "$REPO" fetch --depth 1 origin "$BRANCH"
  git -C "$REPO" reset --hard FETCH_HEAD
elif [ -e "$REPO" ]; then
  # Present but not a git repo (partial clone) — replace it.
  rm -rf "$REPO"
  git clone --depth 1 --branch "$BRANCH" "$REMOTE" "$REPO"
else
  git clone --depth 1 --branch "$BRANCH" "$REMOTE" "$REPO"
fi

mkdir -p "$REPO/data/chains" "$REPO/data/quotes" "$REPO/decision-logs" \
         "${SPECTER_STATE_DIR:-/data/.specter_state}"

echo "SPECTER repo synced: $(git -C "$REPO" rev-parse --short HEAD)"
