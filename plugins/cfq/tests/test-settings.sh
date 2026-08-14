#!/usr/bin/env bash
# Self-test for scripts/cfq-settings.sh. No framework, no fixtures — just `bash tests/test-settings.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
settings_sh="$repo_root/scripts/cfq-settings.sh"

home=$(mktemp -d)
trap 'rm -rf "$home"' EXIT

# 1. Fresh install: list has telemetrySyncRepo, not planPreferredPlugins
list=$(HOME="$home" bash "$settings_sh" list)
[ "$(jq 'has("telemetrySyncRepo")' <<<"$list")" = "true" ] \
  || { echo "FAIL: fresh install missing telemetrySyncRepo"; exit 1; }
[ "$(jq 'has("planPreferredPlugins")' <<<"$list")" = "false" ] \
  || { echo "FAIL: fresh install still has planPreferredPlugins"; exit 1; }

# 2. Legacy settings.json: has planPreferredPlugins, lacks telemetrySyncRepo
legacy_home=$(mktemp -d)
mkdir -p "$legacy_home/.claude/code-for-queue"
echo '{"stopPct":42,"planPreferredPlugins":["x"]}' \
  >"$legacy_home/.claude/code-for-queue/settings.json"

got=$(HOME="$legacy_home" bash "$settings_sh" get telemetrySyncRepo)
[ "$got" = "" ] || { echo "FAIL: legacy telemetrySyncRepo = '$got', want empty"; exit 1; }

got=$(HOME="$legacy_home" bash "$settings_sh" get stopPct)
[ "$got" = "42" ] || { echo "FAIL: legacy stopPct = '$got', want 42 (file beats default)"; exit 1; }

legacy_list=$(HOME="$legacy_home" bash "$settings_sh" list)
[ "$(jq 'has("planPreferredPlugins")' <<<"$legacy_list")" = "false" ] \
  || { echo "FAIL: legacy list still shows planPreferredPlugins"; exit 1; }
rm -rf "$legacy_home"

# 3. set telemetrySyncRepo: absolute writes, empty disables, relative fails
HOME="$home" bash "$settings_sh" set telemetrySyncRepo /tmp/x
got=$(HOME="$home" bash "$settings_sh" get telemetrySyncRepo)
[ "$got" = "/tmp/x" ] || { echo "FAIL: set absolute path -> got '$got'"; exit 1; }

HOME="$home" bash "$settings_sh" set telemetrySyncRepo ""
got=$(HOME="$home" bash "$settings_sh" get telemetrySyncRepo)
[ "$got" = "" ] || { echo "FAIL: set empty -> got '$got'"; exit 1; }

if HOME="$home" bash "$settings_sh" set telemetrySyncRepo relativ 2>/dev/null; then
  echo "FAIL: set relative path should fail"; exit 1
fi

# 4. Env override beats file
got=$(HOME="$home" CFQ_TELEMETRY_SYNC_REPO=/tmp/y bash "$settings_sh" get telemetrySyncRepo)
[ "$got" = "/tmp/y" ] || { echo "FAIL: env override -> got '$got'"; exit 1; }

# 5. Unrelated assertions still hold
got=$(HOME="$home" bash "$settings_sh" get stopPct)
[ "$got" = "40" ] || { echo "FAIL: default stopPct = '$got', want 40"; exit 1; }

if HOME="$home" bash "$settings_sh" set grillMode klassisch 2>/dev/null; then
  echo "FAIL: set grillMode klassisch should fail"; exit 1
fi

echo PASS
