#!/usr/bin/env bash
set -u

REPO="${ORMAH_TEST_REPO:-$HOME/ormah-server-side-test}"
PORT="${ORMAH_TEST_PORT:-8793}"
BASE="${ORMAH_BACKUP_UX_DIR:-$HOME/ormah-backup-ux}"
MEMORY_DIR="$BASE/memory"
BACKUP_DIR="$BASE/backups"
LOG="/tmp/ormah-backup-ux-check-$(date +%Y%m%d-%H%M%S).log"
SERVER_LOG="$BASE/server.log"
SERVER_PID=""

exec > >(tee "$LOG") 2>&1

checkpoint() {
  printf '\n===== %s =====\n' "$1"
}

run() {
  printf '+ %s\n' "$*"
  "$@"
  rc=$?
  printf '[exit=%s]\n' "$rc"
  return "$rc"
}

fail() {
  printf '[FAIL] %s\n' "$1"
  cleanup
  exit 1
}

pass() {
  printf '[PASS] %s\n' "$1"
}

cleanup() {
  if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT

export ORMAH_MEMORY_DIR="$MEMORY_DIR"
export ORMAH_BACKUP_DIR="$BACKUP_DIR"
export ORMAH_PORT="$PORT"

checkpoint "identity"
run whoami
run date
printf 'LOG=%s\n' "$LOG"
printf 'BASE=%s\n' "$BASE"
printf 'MEMORY_DIR=%s\n' "$MEMORY_DIR"
printf 'BACKUP_DIR=%s\n' "$BACKUP_DIR"
printf 'PORT=%s\n' "$PORT"

checkpoint "repo"
cd "$REPO" || fail "repo not found: $REPO"
run git branch --show-current
run git log --oneline -5
run git status --short

checkpoint "runtime"
rm -rf .venv
UV_BIN="$(command -v uv)"
if [ -z "$UV_BIN" ]; then
  fail "uv not found"
fi
PY311="$(uv python find 3.11 2>/dev/null || true)"
if [ -z "$PY311" ]; then
  run uv python install 3.11 || fail "failed to install Python 3.11 with uv"
  PY311="$(uv python find 3.11 2>/dev/null || true)"
fi
if [ -z "$PY311" ]; then
  fail "Python 3.11 not available"
fi

env PATH="$(dirname "$UV_BIN"):$(dirname "$PY311")" \
  "$UV_BIN" run --python "$PY311" --extra litellm ormah --version || fail "failed to build runtime"
export PATH="$PWD/.venv/bin:$PATH"
run which ormah || fail "ormah command not found"
run ormah --version || fail "ormah version failed"

checkpoint "isolated dirs"
rm -rf "$BASE"
mkdir -p "$MEMORY_DIR/nodes"
run find "$BASE" -maxdepth 3 -type d | sort

checkpoint "empty store UX"
EMPTY_STATUS="$(ormah backup status 2>&1)"
printf '%s\n' "$EMPTY_STATUS"
printf '%s\n' "$EMPTY_STATUS" | grep -q 'Backup due now: no (no memory nodes yet)' \
  || fail "empty status did not explain no memory nodes"
pass "empty backup status explains no memory nodes"

EMPTY_LIST="$(ormah backup list 2>&1)"
printf '%s\n' "$EMPTY_LIST"
printf '%s\n' "$EMPTY_LIST" | grep -q 'No Ormah memory backups found.' \
  || fail "empty list did not say no backups found"
pass "empty backup list is clear"

checkpoint "automatic backup skips empty store"
nohup ormah server start > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
printf 'server_pid=%s\n' "$SERVER_PID"
sleep 10

EMPTY_AUTO_LIST="$(ormah backup list 2>&1)"
printf '%s\n' "$EMPTY_AUTO_LIST"
printf '%s\n' "$EMPTY_AUTO_LIST" | grep -q 'No Ormah memory backups found.' \
  || fail "automatic backup created a backup for an empty memory store"
pass "automatic backup skipped empty memory store"

checkpoint "create memory"
run ormah remember "Backup UX test memory. This should survive restore." \
  --title "Backup UX Test" \
  --type fact \
  --space backup-ux || fail "failed to create memory"
run find "$MEMORY_DIR/nodes" -type f -name '*.md' | sort

checkpoint "automatic backup creates when memory exists"
run ormah server stop || true
SERVER_PID=""
sleep 2
nohup ormah server start > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
printf 'server_pid=%s\n' "$SERVER_PID"
sleep 10

BACKUP_LIST="$(ormah backup list 2>&1)"
printf '%s\n' "$BACKUP_LIST"
BACKUP_NAME="$(printf '%s\n' "$BACKUP_LIST" | awk '/^memory_[0-9]/{print $1; exit}')"
if [ -z "$BACKUP_NAME" ]; then
  fail "automatic backup was not created after a memory existed"
fi
pass "automatic backup created $BACKUP_NAME"

run find "$BACKUP_DIR/$BACKUP_NAME" -maxdepth 2 -type f | sort
if [ -f "$BACKUP_DIR/$BACKUP_NAME/index.db" ]; then
  fail "backup unexpectedly included index.db"
fi
if [ -f "$BACKUP_DIR/$BACKUP_NAME/.env" ]; then
  fail "backup unexpectedly included .env"
fi
pass "backup excludes derived index and env files"

checkpoint "restore refuses while server running"
RESTORE_RUNNING="$(ormah backup restore "$BACKUP_NAME" --yes 2>&1)"
RESTORE_RUNNING_RC=$?
printf '%s\n' "$RESTORE_RUNNING"
printf 'RESTORE_RUNNING_EXIT_CODE=%s\n' "$RESTORE_RUNNING_RC"
if [ "$RESTORE_RUNNING_RC" -eq 0 ]; then
  fail "restore succeeded while server was running"
fi
printf '%s\n' "$RESTORE_RUNNING" | grep -q 'Stop the Ormah server before restoring' \
  || fail "restore refusal did not explain how to proceed"
pass "restore refuses while server is running"

checkpoint "restore after stop"
run ormah server stop || true
SERVER_PID=""
sleep 2
run find "$MEMORY_DIR/nodes" -type f -name '*.md' -delete
NODE_COUNT_AFTER_DELETE="$(find "$MEMORY_DIR/nodes" -type f -name '*.md' | wc -l)"
printf 'NODE_COUNT_AFTER_DELETE=%s\n' "$NODE_COUNT_AFTER_DELETE"
if [ "$NODE_COUNT_AFTER_DELETE" -ne 0 ]; then
  fail "failed to delete test memory before restore"
fi

RESTORE_OUTPUT="$(ormah backup restore "$BACKUP_NAME" --yes 2>&1)"
RESTORE_RC=$?
printf '%s\n' "$RESTORE_OUTPUT"
printf 'RESTORE_EXIT_CODE=%s\n' "$RESTORE_RC"
if [ "$RESTORE_RC" -ne 0 ]; then
  fail "restore failed after server stop"
fi
printf '%s\n' "$RESTORE_OUTPUT" | grep -q "Restored backup: $BACKUP_NAME" \
  || fail "restore output did not confirm restored backup"
printf '%s\n' "$RESTORE_OUTPUT" | grep -q 'Safety backup of previous memory:' \
  || fail "restore output did not mention safety backup"
printf '%s\n' "$RESTORE_OUTPUT" | grep -q 'Rebuilt search index from 1 nodes' \
  || fail "restore output did not mention index rebuild"
pass "restore UX confirms safety backup and index rebuild"

RESTORED_NODE_COUNT="$(find "$MEMORY_DIR/nodes" -type f -name '*.md' | wc -l)"
printf 'RESTORED_NODE_COUNT=%s\n' "$RESTORED_NODE_COUNT"
if [ "$RESTORED_NODE_COUNT" -ne 1 ]; then
  fail "restore did not bring back exactly one node"
fi
pass "restore brought memory file back"

checkpoint "final status"
run ormah backup status || fail "backup status failed"
run ormah backup list || fail "backup list failed"

checkpoint "done"
pass "all backup UX checks passed"
printf 'Copy this log back: %s\n' "$LOG"
