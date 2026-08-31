#!/usr/bin/env bash
# Self-test for scripts/cfq-pfq-preflight.sh. No framework, no fixtures beyond what's built here —
# just `bash tests/test-pfq-preflight.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT

# ------------------------------------------------------------ call-counting copy ------
# Copies the whole scripts/ dir so cfq-pfq-preflight.sh's own script_dir resolution (and every
# sibling script it shells out to, e.g. cfq-maintenance.sh) resolves inside the copy, then swaps
# cfq-settings.sh for a wrapper that logs every subcommand before delegating to the real binary.
scripts_copy="$tmp/scripts"
cp -r "$repo_root/scripts" "$scripts_copy"
mv "$scripts_copy/cfq-settings.sh" "$scripts_copy/cfq-settings-real.sh"
count_log="$tmp/settings-calls.log"
: > "$count_log"
cat > "$scripts_copy/cfq-settings.sh" <<EOF
#!/usr/bin/env bash
set -eu
d="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
echo "\$1" >> "$count_log"
exec "\$d/cfq-settings-real.sh" "\$@"
EOF
chmod +x "$scripts_copy/cfq-settings.sh"
pf="$scripts_copy/cfq-pfq-preflight.sh"

# ------------------------------------------------------------ fresh, unregistered repo -
fresh="$tmp/fresh"; mkdir -p "$fresh"; git init -q "$fresh"

out=$(HOME="$home" bash "$pf" "$fresh")
[ "$(jq -r .status <<<"$out")" = "OK" ] || { echo "FAIL: fresh repo status = $out"; exit 1; }
[ "$(jq -r .repo.known <<<"$out")" = "false" ] || { echo "FAIL: fresh repo should be known=false: $out"; exit 1; }
[ "$(jq -c .queue.openBatches <<<"$out")" = "[]" ] || { echo "FAIL: fresh repo openBatches should be []: $out"; exit 1; }

# ------------------------------------------------------------ non-git path -------------
out=$(HOME="$home" bash "$pf" "$tmp/does-not-exist")
[ "$(jq -r .status <<<"$out")" = "NO_REPO" ] || { echo "FAIL: non-git status = $out"; exit 1; }

# ------------------------------------------------------------ known repo + open batches -
reg="$tmp/reg"; mkdir -p "$reg"; git init -q "$reg"
HOME="$home" bash "$scripts_copy/cfq-registry.sh" add "$reg" >/dev/null

qdir="$reg/.claude/cfq/impl"
mkdir -p "$qdir/2026-02-01-a" "$qdir/2026-02-01-b" "$qdir/done/2026-02-01-archived" "$qdir/2026-02-01-empty"
touch "$qdir/2026-02-01-a/01-x.md" "$qdir/2026-02-01-a/02-y.md"
touch "$qdir/2026-02-01-b/01-x.md"
echo high > "$qdir/2026-02-01-b/.priority"
echo 2026-02-01-a > "$qdir/2026-02-01-b/.dependsOn"
touch "$qdir/done/2026-02-01-archived/01-x.md"
# 2026-02-01-empty: batch dir exists but has zero open NN-*.md phases -> must be excluded (open>0)

out=$(HOME="$home" bash "$pf" "$reg")
[ "$(jq -r .repo.known <<<"$out")" = "true" ] || { echo "FAIL: registered repo should be known=true: $out"; exit 1; }
regknown=$(HOME="$home" bash "$scripts_copy/cfq-registry.sh" list | grep -qxF "$reg" && echo true || echo false)
[ "$regknown" = "true" ] || { echo "FAIL: test setup broken, registry doesn't list $reg"; exit 1; }

got=$(jq -S -c '.queue.openBatches | sort_by(.name)' <<<"$out")
want=$(jq -S -c -n '[
  {name:"2026-02-01-a", priority:"", open:2, dependsOn:[]},
  {name:"2026-02-01-b", priority:"high", open:1, dependsOn:["2026-02-01-a"]}
] | sort_by(.name)')
[ "$got" = "$want" ] || { echo "FAIL: openBatches = $got, want $want"; exit 1; }

# ------------------------------------------------------------ maintenance vocabulary ---
git -C "$reg" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m init

out=$(HOME="$home" CFQ_MAINTENANCE_EVERY=0 bash "$pf" "$reg")
[ "$(jq -r .maintenance.status <<<"$out")" = "OFF" ] || { echo "FAIL: maintenance OFF: $out"; exit 1; }
[ "$(jq -r .maintenance.n <<<"$out")" = "null" ] || { echo "FAIL: maintenance.n should be null when OFF: $out"; exit 1; }

out=$(HOME="$home" bash "$pf" "$reg")
direct=$(HOME="$home" bash "$scripts_copy/cfq-maintenance.sh" due "$reg")
[ "$(jq -r .maintenance.status <<<"$out") $(jq -r .maintenance.n <<<"$out")" = "$direct" ] \
  || { echo "FAIL: maintenance field != direct cfq-maintenance.sh output: $out vs $direct"; exit 1; }

# ------------------------------------------------------------ security.available -------
stubbin="$tmp/stubbin"; mkdir -p "$stubbin"
# Symlink farm of the real PATH minus gh/tea, so the rest of the toolchain (bash, jq, git,
# coreutils, ...) stays reachable while gh/tea presence is fully controlled by $stubbin.
bindir="$tmp/bindir"; mkdir -p "$bindir"
old_ifs=$IFS; IFS=:
for d in $PATH; do
  IFS=$old_ifs
  [ -d "$d" ] || { IFS=:; continue; }
  for f in "$d"/*; do
    [ -f "$f" ] && [ -x "$f" ] || continue
    b=$(basename "$f")
    [ "$b" = gh ] && continue
    [ "$b" = tea ] && continue
    [ -e "$bindir/$b" ] && continue
    ln -s "$f" "$bindir/$b"
  done
  IFS=:
done
IFS=$old_ifs

out=$(HOME="$home" PATH="$stubbin:$bindir" bash "$pf" "$reg")
[ "$(jq -r .security.available <<<"$out")" = "false" ] || { echo "FAIL: no gh/tea on PATH should give security.available=false: $out"; exit 1; }

cat > "$stubbin/gh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$stubbin/gh"
out=$(HOME="$home" PATH="$stubbin:$bindir" bash "$pf" "$reg")
[ "$(jq -r .security.available <<<"$out")" = "true" ] || { echo "FAIL: gh on PATH should give security.available=true: $out"; exit 1; }

# ------------------------------------------------------------ one settings.sh call -----
: > "$count_log"
out=$(HOME="$home" bash "$pf" "$reg")
list_calls=$(grep -cx list "$count_log" || true)
[ "$list_calls" = "1" ] || { echo "FAIL: expected exactly 1 'list' cfq-settings.sh call, got $list_calls (log: $(cat "$count_log"))"; exit 1; }
for k in planModels allowAnyModel planExploreModel planExploreModelComplex planBlockedPlugins \
         grillMode useMattpocockGrilling usePonytailAudit codeLanguage docLanguages docLevel; do
  jq -e --arg k "$k" '(.planningPolicy + .language) | has($k)' <<<"$out" >/dev/null \
    || { echo "FAIL: batched settings call missing key '$k': $out"; exit 1; }
done
jq -e '.reporting | has("reportDir") and has("htmlReport")' <<<"$out" >/dev/null \
  || { echo "FAIL: batched settings call missing reporting object: $out"; exit 1; }

# ------------------------------------------------------------ deterministic ------------
out1=$(HOME="$home" bash "$pf" "$reg")
out2=$(HOME="$home" bash "$pf" "$reg")
[ "$out1" = "$out2" ] || { echo "FAIL: two runs on the same fixture produced different output"; exit 1; }

# ------------------------------------------------------------ read-only ----------------
marker="$tmp/marker"; touch "$marker"; sleep 1
HOME="$home" bash "$pf" "$reg" >/dev/null
changed=$(find "$reg" -newer "$marker")
[ -z "$changed" ] || { echo "FAIL: run modified files under the fixture repo: $changed"; exit 1; }

echo PASS
