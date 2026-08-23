#!/usr/bin/env bash
# Self-test for scripts/cfq-settings.sh. No framework, no fixtures — just `bash tests/test-settings.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
settings_sh="$repo_root/scripts/cfq-settings.sh"

# This repo's own .claude/settings.json sets CFQ_* env vars for its own dogfooding (e.g.
# CFQ_DOC_LEVEL) — strip them so default-value assertions below see real defaults, not this
# repo's config. Assertions that test env overrides still set their own CFQ_* var inline per call.
for v in "${!CFQ_@}"; do unset "$v"; done

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
[ "$got" = "42" ] || { echo "FAIL: legacy stopPct = '$got', want 42 (normal key, file value honored)"; exit 1; }

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
[ "$got" = "60" ] || { echo "FAIL: default stopPct = '$got', want 60"; exit 1; }

if HOME="$home" bash "$settings_sh" set grillMode klassisch 2>/dev/null; then
  echo "FAIL: set grillMode klassisch should fail"; exit 1
fi

# 5b. stopPct is a normal key now: set/get round-trip, boundary validation, malformed env falls back
HOME="$home" bash "$settings_sh" set stopPct 45
got=$(HOME="$home" bash "$settings_sh" get stopPct)
[ "$got" = "45" ] || { echo "FAIL: set stopPct 45 -> got '$got'"; exit 1; }

fresh_home=$(mktemp -d)
got=$(HOME="$fresh_home" bash "$settings_sh" get stopPct)
[ "$got" = "60" ] || { echo "FAIL: default stopPct on fresh HOME = '$got', want 60"; exit 1; }
rm -rf "$fresh_home"

if HOME="$home" bash "$settings_sh" set stopPct -1 2>/dev/null; then
  echo "FAIL: set stopPct -1 should fail"; exit 1
fi
if HOME="$home" bash "$settings_sh" set stopPct 101 2>/dev/null; then
  echo "FAIL: set stopPct 101 should fail"; exit 1
fi
HOME="$home" bash "$settings_sh" set stopPct 0
got=$(HOME="$home" bash "$settings_sh" get stopPct)
[ "$got" = "0" ] || { echo "FAIL: set stopPct 0 -> got '$got'"; exit 1; }
HOME="$home" bash "$settings_sh" set stopPct 100
got=$(HOME="$home" bash "$settings_sh" get stopPct)
[ "$got" = "100" ] || { echo "FAIL: set stopPct 100 -> got '$got'"; exit 1; }
HOME="$home" bash "$settings_sh" set stopPct 60

got=$(HOME="$home" CFQ_STOP_PCT=25 bash "$settings_sh" get stopPct)
[ "$got" = "25" ] || { echo "FAIL: env override stopPct -> got '$got'"; exit 1; }

got=$(HOME="$home" CFQ_STOP_PCT=abc bash "$settings_sh" get stopPct)
[ "$got" = "60" ] || { echo "FAIL: malformed CFQ_STOP_PCT -> got '$got', want 60"; exit 1; }

got=$(HOME="$home" bash "$settings_sh" list | jq -r '.stopPct')
[ "$got" = "60" ] || { echo "FAIL: list stopPct on fresh install = '$got', want 60"; exit 1; }

# 5c. phaseContextGrowth: default object (valid JSON, not stringified), round-trip
got=$(HOME="$home" bash "$settings_sh" get phaseContextGrowth)
[ "$got" = '{"S":7,"M":15,"L":25}' ] || { echo "FAIL: default phaseContextGrowth = '$got'"; exit 1; }

HOME="$home" bash "$settings_sh" set phaseContextGrowth '{"S":7,"M":20,"L":25}'
got=$(HOME="$home" bash "$settings_sh" get phaseContextGrowth)
[ "$got" = '{"S":7,"M":20,"L":25}' ] || { echo "FAIL: set phaseContextGrowth round-trip -> got '$got'"; exit 1; }
HOME="$home" bash "$settings_sh" set phaseContextGrowth '{"S":7,"M":15,"L":25}'

# 5d. CFQ_SCAN_ROOTS is comma-delimited now (uniform array env delimiter)
got=$(HOME="$home" CFQ_SCAN_ROOTS=a,b bash "$settings_sh" get scanRoots)
[ "$got" = "a,b" ] || { echo "FAIL: CFQ_SCAN_ROOTS comma round-trip -> got '$got'"; exit 1; }

# 5e. gitStatePolicy: default, set, invalid
got=$(HOME="$home" bash "$settings_sh" get gitStatePolicy)
[ "$got" = "local" ] || { echo "FAIL: default gitStatePolicy = '$got', want local"; exit 1; }

HOME="$home" bash "$settings_sh" set gitStatePolicy trackable
got=$(HOME="$home" bash "$settings_sh" get gitStatePolicy)
[ "$got" = "trackable" ] || { echo "FAIL: set gitStatePolicy trackable -> got '$got'"; exit 1; }

if HOME="$home" bash "$settings_sh" set gitStatePolicy bogus 2>/dev/null; then
  echo "FAIL: set gitStatePolicy bogus should fail"; exit 1
fi
HOME="$home" bash "$settings_sh" set gitStatePolicy local

# 5f. Regression guard: every pre-existing key's default is unchanged by the schema rewrite.
reg_home=$(mktemp -d)
declare -A want=(
  [grillMode]=stepwise
  [planModels]="opus,fable"
  [implModels]=sonnet
  [planExploreModel]=haiku
  [allowAnyModel]=false
  [scanRoots]="~/git"
  [useMattpocockGrilling]=false
  [usePonytailAudit]=false
  [codeLanguage]=en
  [docLanguages]=""
  [docLevel]=minimal
  [maintenanceEvery]=50
  [branchPerBatch]=true
  [changelogFile]="cfq.changelog.yml"
  [htmlReport]=false
  [planBlockedPlugins]=superpowers
  [implBlockedPlugins]=superpowers
  [telemetrySyncRepo]=""
  [setupDone]=false
)
for k in "${!want[@]}"; do
  got=$(HOME="$reg_home" bash "$settings_sh" get "$k")
  [ "$got" = "${want[$k]}" ] || { echo "FAIL: regression default $k = '$got', want '${want[$k]}'"; exit 1; }
done
rm -rf "$reg_home"

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

# 8. branchPerBatch, changelogFile, htmlReport: defaults, boolean validation, arbitrary string
list=$(HOME="$home" bash "$settings_sh" list)
[ "$(jq -r '.branchPerBatch' <<<"$list")" = "true" ] \
  || { echo "FAIL: default branchPerBatch = $(jq -r '.branchPerBatch' <<<"$list"), want true"; exit 1; }
[ "$(jq -r '.changelogFile' <<<"$list")" = "cfq.changelog.yml" ] \
  || { echo "FAIL: default changelogFile = $(jq -r '.changelogFile' <<<"$list"), want cfq.changelog.yml"; exit 1; }
[ "$(jq -r '.htmlReport' <<<"$list")" = "false" ] \
  || { echo "FAIL: default htmlReport = $(jq -r '.htmlReport' <<<"$list"), want false"; exit 1; }

if HOME="$home" bash "$settings_sh" set branchPerBatch nope 2>/dev/null; then
  echo "FAIL: set branchPerBatch nope should fail"; exit 1
fi
if HOME="$home" bash "$settings_sh" set htmlReport nope 2>/dev/null; then
  echo "FAIL: set htmlReport nope should fail"; exit 1
fi

HOME="$home" bash "$settings_sh" set branchPerBatch false
got=$(HOME="$home" bash "$settings_sh" get branchPerBatch)
[ "$got" = "false" ] || { echo "FAIL: set branchPerBatch false -> got '$got'"; exit 1; }

HOME="$home" bash "$settings_sh" set htmlReport true
got=$(HOME="$home" bash "$settings_sh" get htmlReport)
[ "$got" = "true" ] || { echo "FAIL: set htmlReport true -> got '$got'"; exit 1; }

HOME="$home" bash "$settings_sh" set changelogFile my.changelog.yml
got=$(HOME="$home" bash "$settings_sh" get changelogFile)
[ "$got" = "my.changelog.yml" ] || { echo "FAIL: set changelogFile -> got '$got'"; exit 1; }

HOME="$home" bash "$settings_sh" set changelogFile ""
got=$(HOME="$home" bash "$settings_sh" get changelogFile)
[ "$got" = "" ] || { echo "FAIL: set changelogFile empty -> got '$got'"; exit 1; }

# 9. planExploreModel: default, set, env override
got=$(HOME="$home" bash "$settings_sh" get planExploreModel)
[ "$got" = "haiku" ] || { echo "FAIL: default planExploreModel = '$got', want haiku"; exit 1; }

HOME="$home" bash "$settings_sh" set planExploreModel opus
got=$(HOME="$home" bash "$settings_sh" get planExploreModel)
[ "$got" = "opus" ] || { echo "FAIL: set planExploreModel opus -> got '$got'"; exit 1; }

got=$(HOME="$home" CFQ_PLAN_EXPLORE_MODEL=haiku-fast bash "$settings_sh" get planExploreModel)
[ "$got" = "haiku-fast" ] || { echo "FAIL: env override planExploreModel -> got '$got'"; exit 1; }

echo PASS
