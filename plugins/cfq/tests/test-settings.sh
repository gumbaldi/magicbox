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

# 6. maintenanceEvery: default, set 0, invalid, env override
got=$(HOME="$home" bash "$settings_sh" get maintenanceEvery)
[ "$got" = "50" ] || { echo "FAIL: default maintenanceEvery = '$got', want 50"; exit 1; }

HOME="$home" bash "$settings_sh" set maintenanceEvery 0
got=$(HOME="$home" bash "$settings_sh" get maintenanceEvery)
[ "$got" = "0" ] || { echo "FAIL: set maintenanceEvery 0 -> got '$got'"; exit 1; }

if HOME="$home" bash "$settings_sh" set maintenanceEvery abc 2>/dev/null; then
  echo "FAIL: set maintenanceEvery abc should fail"; exit 1
fi

got=$(HOME="$home" CFQ_MAINTENANCE_EVERY=10 bash "$settings_sh" get maintenanceEvery)
[ "$got" = "10" ] || { echo "FAIL: env override maintenanceEvery -> got '$got'"; exit 1; }

# 7. codeLanguage, docLanguages, docLevel: defaults, set, invalid, env override, gone key
got=$(HOME="$home" bash "$settings_sh" get codeLanguage)
[ "$got" = "en" ] || { echo "FAIL: default codeLanguage = '$got', want en"; exit 1; }

got=$(HOME="$home" bash "$settings_sh" get docLanguages)
[ "$got" = "" ] || { echo "FAIL: default docLanguages = '$got', want empty"; exit 1; }

got=$(HOME="$home" bash "$settings_sh" get docLevel)
[ "$got" = "minimal" ] || { echo "FAIL: default docLevel = '$got', want minimal"; exit 1; }

HOME="$home" bash "$settings_sh" set docLevel standard
got=$(HOME="$home" bash "$settings_sh" get docLevel)
[ "$got" = "standard" ] || { echo "FAIL: set docLevel standard -> got '$got'"; exit 1; }

if HOME="$home" bash "$settings_sh" set docLevel bogus 2>/dev/null; then
  echo "FAIL: set docLevel bogus should fail"; exit 1
fi

HOME="$home" bash "$settings_sh" set codeLanguage de
got=$(HOME="$home" bash "$settings_sh" get codeLanguage)
[ "$got" = "de" ] || { echo "FAIL: set codeLanguage de -> got '$got'"; exit 1; }

if HOME="$home" bash "$settings_sh" set codeLanguage "de DE" 2>/dev/null; then
  echo "FAIL: set codeLanguage 'de DE' should fail"; exit 1
fi

HOME="$home" bash "$settings_sh" set docLanguages de,fr
got=$(HOME="$home" bash "$settings_sh" get docLanguages)
[ "$got" = "de,fr" ] || { echo "FAIL: set docLanguages de,fr -> got '$got'"; exit 1; }

got=$(HOME="$home" CFQ_CODE_LANGUAGE=pt-BR bash "$settings_sh" get codeLanguage)
[ "$got" = "pt-BR" ] || { echo "FAIL: env override codeLanguage -> got '$got'"; exit 1; }

got=$(HOME="$home" CFQ_DOC_LANGUAGES=es bash "$settings_sh" get docLanguages)
[ "$got" = "es" ] || { echo "FAIL: env override docLanguages -> got '$got'"; exit 1; }

got=$(HOME="$home" CFQ_DOC_LEVEL=full bash "$settings_sh" get docLevel)
[ "$got" = "full" ] || { echo "FAIL: env override docLevel -> got '$got'"; exit 1; }

got=$(HOME="$home" bash "$settings_sh" get ponytailAuditEvery)
[ "$got" = "null" ] || { echo "FAIL: ponytailAuditEvery still present, got '$got'"; exit 1; }

echo PASS
