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
echo '{"stopUsed":42,"planPreferredPlugins":["x"]}' \
  >"$legacy_home/.claude/code-for-queue/settings.json"

got=$(HOME="$legacy_home" bash "$settings_sh" get telemetrySyncRepo)
[ "$got" = "" ] || { echo "FAIL: legacy telemetrySyncRepo = '$got', want empty"; exit 1; }

got=$(HOME="$legacy_home" bash "$settings_sh" get stopUsed)
[ "$got" = "42" ] || { echo "FAIL: legacy stopUsed = '$got', want 42 (normal key, file value honored)"; exit 1; }

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
got=$(HOME="$home" bash "$settings_sh" get stopUsed)
[ "$got" = "100000" ] || { echo "FAIL: default stopUsed = '$got', want 100000"; exit 1; }

if HOME="$home" bash "$settings_sh" set grillMode klassisch 2>/dev/null; then
  echo "FAIL: set grillMode klassisch should fail"; exit 1
fi

# 5b. stopUsed: default, set/round-trip, special values -1 and 0, malformed env falls back, list
got=$(HOME="$home" bash "$settings_sh" get stopUsed)
[ "$got" = "100000" ] || { echo "FAIL: default stopUsed = '$got', want 100000"; exit 1; }

fresh_home=$(mktemp -d)
got=$(HOME="$fresh_home" bash "$settings_sh" get stopUsed)
[ "$got" = "100000" ] || { echo "FAIL: default stopUsed on fresh HOME = '$got', want 100000"; exit 1; }
rm -rf "$fresh_home"

HOME="$home" bash "$settings_sh" set stopUsed 50000
got=$(HOME="$home" bash "$settings_sh" get stopUsed)
[ "$got" = "50000" ] || { echo "FAIL: set stopUsed 50000 -> got '$got'"; exit 1; }

# routine case
HOME="$home" bash "$settings_sh" set stopUsed 250000
got=$(HOME="$home" bash "$settings_sh" get stopUsed)
[ "$got" = "250000" ] || { echo "FAIL: set stopUsed 250000 -> got '$got'"; exit 1; }

# edge case: 0 (always stop after a phase) is valid, not rejected
HOME="$home" bash "$settings_sh" set stopUsed 0
got=$(HOME="$home" bash "$settings_sh" get stopUsed)
[ "$got" = "0" ] || { echo "FAIL: set stopUsed 0 -> got '$got'"; exit 1; }

# edge case: -1 (never stop) is valid, not rejected
HOME="$home" bash "$settings_sh" set stopUsed -1
got=$(HOME="$home" bash "$settings_sh" get stopUsed)
[ "$got" = "-1" ] || { echo "FAIL: set stopUsed -1 -> got '$got'"; exit 1; }

# failure case: below -1 is rejected
if HOME="$home" bash "$settings_sh" set stopUsed -2 2>/dev/null; then
  echo "FAIL: set stopUsed -2 should fail"; exit 1
fi

HOME="$home" bash "$settings_sh" set stopUsed 100000

got=$(HOME="$home" CFQ_STOP_USED=75000 bash "$settings_sh" get stopUsed)
[ "$got" = "75000" ] || { echo "FAIL: env override stopUsed -> got '$got'"; exit 1; }

got=$(HOME="$home" CFQ_STOP_USED=abc bash "$settings_sh" get stopUsed)
[ "$got" = "100000" ] || { echo "FAIL: malformed CFQ_STOP_USED -> got '$got', want 100000"; exit 1; }

got=$(HOME="$home" bash "$settings_sh" list | jq -r '.stopUsed')
[ "$got" = "100000" ] || { echo "FAIL: list stopUsed on fresh install = '$got', want 100000"; exit 1; }

# phaseContextGrowth is gone
got=$(HOME="$home" bash "$settings_sh" get phaseContextGrowth)
[ "$got" = "null" ] || { echo "FAIL: phaseContextGrowth still present, got '$got'"; exit 1; }

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
  [implExploreModel]=haiku
  [allowAnyModel]=false
  [scanRoots]="~/git"
  [useMattpocockGrilling]=false
  [usePonytailAudit]=false
  [codeLanguage]=en
  [docLanguages]=""
  [docLevel]=minimal
  [maintenanceEvery]=50
  [branchPerBatch]=true
  [changelogFile]=".claude/cfq/changelog.yml"
  [htmlReport]=false
  [planBlockedPlugins]=superpowers
  [implBlockedPlugins]=superpowers
  [telemetrySyncRepo]=""
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
[ "$(jq -r '.changelogFile' <<<"$list")" = ".claude/cfq/changelog.yml" ] \
  || { echo "FAIL: default changelogFile = $(jq -r '.changelogFile' <<<"$list"), want .claude/cfq/changelog.yml"; exit 1; }
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

# 9b. implExploreModel: default, set, env override
got=$(HOME="$home" bash "$settings_sh" get implExploreModel)
[ "$got" = "haiku" ] || { echo "FAIL: default implExploreModel = '$got', want haiku"; exit 1; }

HOME="$home" bash "$settings_sh" set implExploreModel opus
got=$(HOME="$home" bash "$settings_sh" get implExploreModel)
[ "$got" = "opus" ] || { echo "FAIL: set implExploreModel opus -> got '$got'"; exit 1; }

got=$(HOME="$home" CFQ_IMPL_EXPLORE_MODEL=haiku-fast bash "$settings_sh" get implExploreModel)
[ "$got" = "haiku-fast" ] || { echo "FAIL: env override implExploreModel -> got '$got'"; exit 1; }

# 10. Repo-scoped settings: precedence chain, scope rejection, unset fall-through, legacy
# detection, migrate. Fresh HOME (a prior section already customized maintenanceEvery in
# $home) and a throwaway fixture repo — never the real repo.
repo_home=$(mktemp -d)
fixture=$(mktemp -d)

got=$(HOME="$repo_home" bash "$settings_sh" get --repo "$fixture" --source maintenanceEvery)
[ "$got" = '{"value":50,"source":"default"}' ] \
  || { echo "FAIL: precedence step 1 (default) -> got '$got'"; exit 1; }

HOME="$repo_home" bash "$settings_sh" set maintenanceEvery 20
got=$(HOME="$repo_home" bash "$settings_sh" get --repo "$fixture" --source maintenanceEvery)
[ "$got" = '{"value":20,"source":"global"}' ] \
  || { echo "FAIL: precedence step 2 (global) -> got '$got'"; exit 1; }

HOME="$repo_home" bash "$settings_sh" set --repo "$fixture" maintenanceEvery 5
got=$(HOME="$repo_home" bash "$settings_sh" get --repo "$fixture" --source maintenanceEvery)
[ "$got" = '{"value":5,"source":"repo"}' ] \
  || { echo "FAIL: precedence step 3 (repo) -> got '$got'"; exit 1; }

got=$(HOME="$repo_home" CFQ_MAINTENANCE_EVERY=99 bash "$settings_sh" get --repo "$fixture" --source maintenanceEvery)
[ "$got" = '{"value":99,"source":"env:process"}' ] \
  || { echo "FAIL: precedence step 4 (env) -> got '$got'"; exit 1; }

# scanRoots is global-only; --repo set must fail
if HOME="$repo_home" bash "$settings_sh" set --repo "$fixture" scanRoots /tmp 2>/dev/null; then
  echo "FAIL: set scanRoots --repo should fail (global-only scope)"; exit 1
fi

# unset --repo falls through to the global value
HOME="$repo_home" bash "$settings_sh" unset --repo "$fixture" maintenanceEvery
got=$(HOME="$repo_home" bash "$settings_sh" get --repo "$fixture" --source maintenanceEvery)
[ "$got" = '{"value":20,"source":"global"}' ] \
  || { echo "FAIL: unset --repo fall-through -> got '$got'"; exit 1; }

# Legacy detection: a repo's own .claude/settings.json "env" block is read-only/informational
mkdir -p "$fixture/.claude"
echo '{"env":{"CFQ_DOC_LEVEL":"standard"}}' > "$fixture/.claude/settings.json"
got=$(HOME="$repo_home" CFQ_DOC_LEVEL=standard bash "$settings_sh" list --repo "$fixture" --sources | jq -c '.docLevel')
[ "$got" = '{"value":"standard","source":"env:repo-legacy"}' ] \
  || { echo "FAIL: legacy detection -> got '$got'"; exit 1; }

# migrate writes the equivalent key into <fixture>/.claude/cfq/settings.json via `set --repo`
# and never touches the original .claude/settings.json
legacy_before=$(cat "$fixture/.claude/settings.json")
HOME="$repo_home" bash "$settings_sh" migrate "$fixture" >/dev/null
got=$(jq -r '.docLevel' "$fixture/.claude/cfq/settings.json")
[ "$got" = "standard" ] || { echo "FAIL: migrate docLevel -> got '$got'"; exit 1; }
legacy_after=$(cat "$fixture/.claude/settings.json")
[ "$legacy_before" = "$legacy_after" ] \
  || { echo "FAIL: migrate modified the original .claude/settings.json"; exit 1; }

rm -rf "$fixture" "$repo_home"

# 11. describe: well-formed JSON with type/default/scope/env/description, single key and all keys
got=$(HOME="$home" bash "$settings_sh" describe stopPct)
for field in type default scope env description; do
  [ "$(jq "has(\"$field\")" <<<"$got")" = "true" ] \
    || { echo "FAIL: describe stopPct missing field '$field'"; exit 1; }
done

got=$(HOME="$home" bash "$settings_sh" describe)
[ "$(jq 'to_entries | all(.value | has("type") and has("default") and has("scope") and has("env") and has("description"))' <<<"$got")" = "true" ] \
  || { echo "FAIL: describe (all keys) missing fields somewhere"; exit 1; }

# 12. state store: separate schema-less key/value file, distinct from settings.json
state_home=$(mktemp -d)

got=$(HOME="$state_home" bash "$settings_sh" state get anything)
[ "$got" = "null" ] || { echo "FAIL: state get on missing key -> got '$got', want null"; exit 1; }

HOME="$state_home" bash "$settings_sh" state set setupDone true
got=$(HOME="$state_home" bash "$settings_sh" state get setupDone)
[ "$got" = "true" ] || { echo "FAIL: state set/get setupDone round-trip -> got '$got'"; exit 1; }

# touch settings.json too, then confirm both files exist independently
HOME="$state_home" bash "$settings_sh" set maintenanceEvery 10 >/dev/null
[ -f "$state_home/.claude/code-for-queue/settings.json" ] \
  || { echo "FAIL: settings.json missing after set"; exit 1; }
[ -f "$state_home/.claude/code-for-queue/state.json" ] \
  || { echo "FAIL: state.json missing after state set"; exit 1; }

# setupDone is fully gone from the settings schema — get falls through to its existing
# unknown-key convention (bare "null"), same as any other key absent from $schema
got=$(HOME="$state_home" bash "$settings_sh" get setupDone)
[ "$got" = "null" ] || { echo "FAIL: get setupDone (removed key) -> got '$got', want null"; exit 1; }

if HOME="$state_home" bash "$settings_sh" set setupDone true 2>/dev/null; then
  echo "FAIL: set setupDone should fail (removed from schema)"; exit 1
fi

list=$(HOME="$state_home" bash "$settings_sh" list)
[ "$(jq 'has("setupDone")' <<<"$list")" = "false" ] \
  || { echo "FAIL: list still shows setupDone"; exit 1; }

rm -rf "$state_home"

# 13. securityTimeoutSeconds / securityFindingsCap: documented defaults
got=$(HOME="$home" bash "$settings_sh" get securityTimeoutSeconds)
[ "$got" = "30" ] || { echo "FAIL: default securityTimeoutSeconds = '$got', want 30"; exit 1; }

got=$(HOME="$home" bash "$settings_sh" get securityFindingsCap)
[ "$got" = "20" ] || { echo "FAIL: default securityFindingsCap = '$got', want 20"; exit 1; }

echo PASS
