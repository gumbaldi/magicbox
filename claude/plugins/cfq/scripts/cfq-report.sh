#!/usr/bin/env bash
# Implementation reports per batch. The report lives in the batch directory and travels with it.
# Usage: cfq-report.sh append <batch-dir> <phase-json>
#        cfq-report.sh security <batch-dir> <security-json>
#        cfq-report.sh set-commit <batch-dir> <phase-slug> <sha>
#        cfq-report.sh last-failure <batch-dir> <phase-slug>
#        cfq-report.sh summary <batch-dir>
#        cfq-report.sh html <batch-dir>
#        cfq-report.sh index [--repo <substr>] [--batch <substr>] [--any <substr>] [--text]
#        cfq-report.sh detail <batch-dir>
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-report.sh: jq is required" >&2; exit 1; }

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Shared by html's per-batch report and its collected index.html — one visual language, not two.
report_style_css='body{font-family:system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fff}
@media (prefers-color-scheme: dark){body{color:#e8e8e8;background:#1a1a1a}code{background:#2a2a2a}}
.meta,.summary{color:#666}section.phase{border-left:4px solid #999;padding:0.5rem 1rem;margin:1rem 0}
section.phase.green{border-color:#2a8f4a}section.phase.red{border-color:#c0392b}
.badge{display:inline-block;padding:0.1rem 0.5rem;border-radius:0.3rem;font-size:0.8rem;color:#fff}
.badge.green{background:#2a8f4a}.badge.red{background:#c0392b}.badge.mixed{background:#c98a1b}
code{background:#f0f0f0;padding:0.1rem 0.3rem;border-radius:0.2rem}
.telemetry{color:#666;font-size:0.85rem}.kv{margin-right:0.4rem}
.goal{color:#666;font-style:italic}
section.repo{margin:1.5rem 0}'

# Shared by index/detail: GREEN if no phase ever went red; RED if any phase's most recent attempt
# is still red; MIXED if every phase that ever went red now shows green as its latest attempt.
outcome_def='
  def outcome:
    (.phases // []) as $ph
    | (reduce $ph[] as $p ({}; .[($p.phase // "")] = $p.status)) as $latest
    | if ([$ph[] | select(.status == "red")] | length) == 0 then "GREEN"
      elif ($latest | to_entries | any(.value == "red")) then "RED"
      else "MIXED"
      end;
'

# Batch dir -> containing repo root, stripping the known queue suffixes (canonicalized first so a
# relative batch-dir path resolves the same as an absolute one). Empty string if it isn't nested
# under either suffix.
repo_root_of() {
  local d="${1%/}" abs r
  abs="$(cd "$d" 2>/dev/null && pwd)" || abs="$d"
  r="${abs%/.claude/cfq/impl/done/*}"
  [ "$r" = "$abs" ] && r="${abs%/.claude/cfq/impl/*}"
  [ "$r" = "$abs" ] && r=""
  printf '%s' "$r"
}

# Resolves the path report.html lives (or would live) at for a batch directory, honoring the
# reportDir setting when configured — same resolution `html` and `index --text`'s file:// lines
# both need. Read-only: a caller that's about to write creates the directory itself.
resolve_html_path() {
  local dir="${1%/}" repo_root report_dir
  repo_root="$(repo_root_of "$dir")"
  if [ -n "$repo_root" ]; then
    report_dir=$("$script_dir/cfq-settings.sh" get --repo "$repo_root" reportDir 2>/dev/null || true)
  else
    report_dir=$("$script_dir/cfq-settings.sh" get reportDir 2>/dev/null || true)
  fi
  case "$report_dir" in
    ''|null) printf '%s/report.html' "$dir" ;;
    *) printf '%s/%s/%s.html' "$report_dir" "$(basename "$repo_root")" "$(basename "$dir")" ;;
  esac
}

# report.json is created by whoever writes to it first — planning-time security snapshot or the
# first phase. Same shape in both cases.
ensure_report() {
  [ -f "$1/report.json" ] && return 0
  jq -n --arg repo "$(cd "$1" && git rev-parse --show-toplevel 2>/dev/null || echo '')" \
        --arg batch "$(basename "$1")" \
        --arg started "$(date -Iseconds)" \
        '{repo: $repo, batch: $batch, started: $started, phases: []}' >"$1/report.json"
}

cmd="${1:-}"
case "$cmd" in
  append)
    dir="${2:?usage: cfq-report.sh append <batch-dir> <phase-json>}"
    phase="${3:?usage: cfq-report.sh append <batch-dir> <phase-json>}"
    [ -d "$dir" ] || { echo "cfq-report.sh: no such batch directory: $dir" >&2; exit 1; }
    # The phase field is the plan file's slug (NN-slug) — the same value that later goes to
    # set-commit, last-failure and `changelog commit-message`'s CFQ-Phase trailer. A bare number
    # or an empty value breaks every one of those lookups without an error, so it is refused here,
    # at the only point that sees the value before it is persisted.
    phase_id="$(printf '%s' "$phase" | jq -r '.phase // ""')"
    case "$phase_id" in
      [0-9][0-9]-?*) ;;
      *) echo "cfq-report.sh append: phase must be the full phase slug (NN-slug), got '$phase_id'" >&2; exit 1 ;;
    esac
    f="$dir/report.json"
    ensure_report "$dir"
    jq --argjson p "$phase" '.phases += [$p]' "$f" >"$f.tmp" && mv "$f.tmp" "$f"
    # Telemetry attaches to the entry just written. Never fatal: a missing transcript must not
    # cost the phase its report.
    "$script_dir/cfq-telemetry.sh" record "$dir" phase "$phase_id" || true
    ;;
  security)
    dir="${2:?usage: cfq-report.sh security <batch-dir> <security-json>}"
    snap="${3:?usage: cfq-report.sh security <batch-dir> <security-json>}"
    [ -d "$dir" ] || { echo "cfq-report.sh: no such batch directory: $dir" >&2; exit 1; }
    f="$dir/report.json"
    ensure_report "$dir"
    jq --argjson s "$snap" --arg at "$(date -Iseconds)" \
       '.security = ((.security // []) + [$s + {at: $at}])' "$f" >"$f.tmp" && mv "$f.tmp" "$f"
    ;;
  set-commit)
    dir="${2:?usage: cfq-report.sh set-commit <batch-dir> <phase-slug> <sha>}"
    phase_slug="${3:?usage: cfq-report.sh set-commit <batch-dir> <phase-slug> <sha>}"
    sha="${4:?usage: cfq-report.sh set-commit <batch-dir> <phase-slug> <sha>}"
    [ -d "$dir" ] || { echo "cfq-report.sh: no such batch directory: $dir" >&2; exit 1; }
    f="$dir/report.json"
    [ -f "$f" ] || { echo "cfq-report.sh: no report.json in $dir" >&2; exit 1; }
    jq -e --arg p "$phase_slug" '[.phases[] | select(.phase == $p)] | length > 0' "$f" >/dev/null \
      || { echo "cfq-report.sh set-commit: no phase entry '$phase_slug' in $f — the phase field carries the full phase slug (NN-slug), not the bare number" >&2; exit 1; }
    jq --arg p "$phase_slug" --arg c "$sha" '
      (.phases | to_entries | map(select(.value.phase == $p)) | last.key) as $i
      | .phases[$i].commit = $c
    ' "$f" >"$f.tmp" && mv "$f.tmp" "$f"
    ;;
  last-failure)
    dir="${2:?usage: cfq-report.sh last-failure <batch-dir> <phase-slug>}"
    phase_slug="${3:?usage: cfq-report.sh last-failure <batch-dir> <phase-slug>}"
    f="$dir/report.json"
    if [ ! -f "$f" ]; then
      jq -n '{found: false}'
    else
      jq -c --arg p "$phase_slug" '
        ([.phases[] | select(.phase == $p and .status == "red")] | last) as $e
        | if $e == null then {found: false}
          else {found: true, phase: $e.phase, note: ($e.summary // ""), at: ($e.finished // "")} end
      ' "$f"
    fi
    ;;
  summary)
    dir="${2:?usage: cfq-report.sh summary <batch-dir>}"
    f="$dir/report.json"
    [ -f "$f" ] || exit 1
    jq -r '[ .batch,
             (.phases | length),
             ([.phases[] | select(.status == "green")] | length),
             ([.phases[] | select(.status == "red")] | length),
             ([.phases[].deviations // []] | flatten | length),
             (.phases[-1].finished // .started),
             ([ (.planning.totals.output // 0) ] + [ .phases[].telemetry.totals.output // 0 ] | add),
             (.planning.totals.output // 0),
             ([ (.planning.totals.turns // 0) ] + [ .phases[].telemetry.totals.turns // 0 ] | add),
             (([(.planning.by_model // {} | keys)] + [.phases[] | (.telemetry.by_model // {} | keys)]) | flatten | unique | join(",")),
             (([(.planning.by_effort // {} | keys)] + [.phases[] | (.telemetry.by_effort // {} | keys)]) | flatten | unique | join(","))
           ] | @tsv' "$f"
    ;;
  html)
    dir="${2:?usage: cfq-report.sh html <batch-dir>}"
    dir="${dir%/}"
    f="$dir/report.json"
    [ -f "$f" ] || { echo "cfq-report.sh: no report.json in $dir" >&2; exit 1; }

    repo_root="$(repo_root_of "$dir")"
    if [ -n "$repo_root" ]; then
      report_dir=$("$script_dir/cfq-settings.sh" get --repo "$repo_root" reportDir 2>/dev/null || true)
    else
      report_dir=$("$script_dir/cfq-settings.sh" get reportDir 2>/dev/null || true)
    fi
    out="$(resolve_html_path "$dir")"
    case "$report_dir" in
      ''|null) ;;
      *) mkdir -p "$(dirname "$out")" \
           || { echo "cfq-report.sh: cannot create $(dirname "$out")" >&2; exit 1; } ;;
    esac

    # Phase goal per phase, from its plan file's `## Context` — same extraction as
    # cfq-brief.sh:31-38's k/ctx/n logic, carried over verbatim. Missing plan file -> omitted.
    goals_json="{}"
    while IFS= read -r p; do
      [ -z "$p" ] && continue
      planfile="$dir/done/$p.md"
      [ -f "$planfile" ] || planfile="$dir/$p.md"
      [ -f "$planfile" ] || continue
      goal=$(awk '
        /^## Context/ { k = 1; next }
        k && NF       { ctx = ctx $0 " "; if (++n >= 2) k = 0; next }
        END { print substr(ctx, 1, 220) }
      ' "$planfile")
      [ -n "$goal" ] && goals_json=$(jq -c --arg p "$p" --arg g "$goal" '. + {($p): $g}' <<<"$goals_json")
    done < <(jq -r '[.phases[].phase] | unique | .[]' "$f")

    jq -r --argjson goals "$goals_json" --arg style "$report_style_css" '
      def esc: (. // "") | tostring | @html;
      def section_list(title): if length > 0 then
        "<h4>" + title + "</h4><ul>" + (map("<li>" + esc + "</li>") | join("")) + "</ul>"
      else "" end;
      def kv: "<span class=\"kv\">" + .[0] + " <b>" + (.[1] | tostring | @html) + "</b></span>";
      def telemetry_html:
        (.telemetry // null) as $t
        | if $t == null then "" else
            "<p class=\"telemetry\">" +
            ([ ["Turns", $t.totals.turns],
               ["Out",   $t.totals.output],
               ["In",    ($t.totals.billable_in // 0)],
               ["Cache", ($t.totals.cache_read // 0)],
               ["Dauer", (($t.wallclock_s // 0) | floor | tostring + " s")],
               ["Model", ($t.by_model  | keys | join(", "))],
               ["Effort",($t.by_effort | keys | join(", "))],
               ["Skills",(($t.by_skill | keys | map(select(. != "-")) | join(", ")) // "-")]
             ] | map(kv) | join(" · ")) + "</p>"
          end;
      def phase_html:
        ($goals[(.phase // "")] // "") as $goal
        | "<section class=\"phase " + .status + "\">" +
        "<h3><span class=\"badge " + .status + "\">" + ((.status // "") | ascii_upcase | @html) + "</span> " +
        (.phase | esc) + "</h3>" +
        (if $goal != "" then "<p class=\"goal\">" + ($goal | esc) + "</p>" else "" end) +
        "<p>" + (.summary | esc) + "</p>" +
        telemetry_html +
        ((.deviations // []) | section_list("Deviations")) +
        ((.errors // []) | section_list("Errors")) +
        (if (.verification // "") != "" then "<p class=\"verification\"><code>" + (.verification | esc) + "</code></p>" else "" end) +
        (if (.commit // "") != "" then "<p class=\"commit\">Commit: <code>" + (.commit | esc) + "</code></p>" else "" end) +
        "</section>";
      "<!doctype html><html><head><meta charset=\"utf-8\"><title>" + (.batch | esc) + " report</title><style>" + $style + "</style></head><body>" +
      "<h1>" + (.batch | esc) + "</h1>" +
      "<p class=\"meta\">Repo: " + (.repo | esc) + " · Started: " + (.started | esc) + "</p>" +
      "<p class=\"summary\">Phases: " + (.phases | length | tostring) +
      " · Green: " + ([.phases[] | select(.status == "green")] | length | tostring) +
      " · Red: " + ([.phases[] | select(.status == "red")] | length | tostring) + "</p>" +
      (if (.planning // null) != null then
        "<p class=\"summary\">Planning: " + (.planning.totals.output | tostring) + " out · " +
        (.planning.totals.turns | tostring) + " Turns · " + (.planning.by_model | keys | join(", ")) +
        " · Implementierung: " + ([.phases[].telemetry.totals.output // 0] | add | tostring) + " out</p>"
       else "" end) +
      ([.phases[] | phase_html] | join("")) +
      "</body></html>"
    ' "$f" >"$out.tmp"
    mv "$out.tmp" "$out"
    echo "$out"

    # Collected-tree mode also regenerates the directory-of-everything index.
    if [ -n "$report_dir" ] && [ "$report_dir" != null ]; then
      idx_json=$("$script_dir/cfq-report.sh" index)
      rows="[]"
      while IFS= read -r row; do
        rb=$(basename "$(jq -r '.repo' <<<"$row")")
        b=$(jq -r '.batch' <<<"$row")
        rendered=false
        [ -f "$report_dir/$rb/$b.html" ] && rendered=true
        rows=$(jq -c --argjson row "$row" --arg rb "$rb" --argjson rendered "$rendered" \
          '. + [$row + {repoBase: $rb, rendered: $rendered}]' <<<"$rows")
      done < <(jq -c '.[]' <<<"$idx_json")

      idx_out="$report_dir/index.html"
      jq -r --arg style "$report_style_css" '
        def esc: (. // "") | tostring | @html;
        def row_html:
          "<li><span class=\"badge " + (.status | ascii_downcase) + "\">" + (.status | esc) + "</span> " +
          (if .rendered then "<a href=\"" + (.repoBase | esc) + "/" + (.batch | esc) + ".html\">" + (.batch | esc) + "</a>"
           else (.batch | esc) end) +
          " · " + (.date | esc) + " · " + ((.cost.outputTokens // 0) | tostring) + " out, " +
          ((.cost.turns // 0) | tostring) + " Turns" +
          (if .deviations > 0 then " · " + (.deviations | tostring) + " Deviations" else "" end) +
          "</li>";
        def repo_section:
          "<section class=\"repo\"><h2>" + (.[0].repoBase | esc) + "</h2><ul>" +
          (map(row_html) | join("")) + "</ul></section>";
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>cfq reports</title><style>" + $style + "</style></head><body>" +
        "<h1>cfq reports</h1>" +
        ((group_by(.repoBase) | map(repo_section) | join("")) as $body | if length == 0 then "<p class=\"meta\">No reports yet.</p>" else $body end) +
        "</body></html>"
      ' <<<"$rows" >"$idx_out.tmp"
      mv "$idx_out.tmp" "$idx_out"
    fi
    ;;
  index)
    shift
    repo_filter=""; batch_filter=""; any_filter=""; text_mode=0
    usage="usage: cfq-report.sh index [--repo <substr>] [--batch <substr>] [--any <substr>] [--text]"
    while [ $# -gt 0 ]; do
      case "$1" in
        --repo) repo_filter="${2:?$usage}"; shift 2 ;;
        --batch) batch_filter="${2:?$usage}"; shift 2 ;;
        --any) any_filter="${2:?$usage}"; shift 2 ;;
        --text) text_mode=1; shift ;;
        *) echo "cfq-report.sh: unknown argument: $1" >&2; exit 1 ;;
      esac
    done
    scan_json="$("$script_dir/cfq-scan.sh")"
    # --any matches either the repo path or the batch name — the merge-and-dedupe an ambiguous
    # single argument used to need (two index calls, merged by the caller) collapses into one
    # OR'd selection here, inherently deduped since each batch is visited once.
    meta=$(jq -c --arg repoF "$repo_filter" --arg batchF "$batch_filter" --arg anyF "$any_filter" '
      [ .repos[] as $r
        | $r.batches[]
        | select(.report == true)
        | select($repoF == "" or ($r.path | ascii_downcase | contains($repoF | ascii_downcase)))
        | select($batchF == "" or (.name | ascii_downcase | contains($batchF | ascii_downcase)))
        | select($anyF == "" or ($r.path | ascii_downcase | contains($anyF | ascii_downcase))
                          or (.name | ascii_downcase | contains($anyF | ascii_downcase)))
        | { repo: $r.path, name,
            path: ($r.path + (if .archived then "/.claude/cfq/impl/done/" else "/.claude/cfq/impl/" end) + .name + "/report.json") }
      ]' <<<"$scan_json")
    if [ "$(jq 'length' <<<"$meta")" -eq 0 ]; then
      rows='[]'
    else
      mapfile -t report_files < <(jq -r '.[].path' <<<"$meta")
      rows=$(jq -s -c --argjson meta "$meta" "$outcome_def"'
        [ range(0; length) as $i
          | .[$i] as $r
          | $meta[$i] as $m
          | {
              batch: $m.name,
              repo: $m.repo,
              date: (($r.phases[-1].finished // $r.started) // ""),
              status: ($r | outcome),
              deviations: ([$r.phases[]?.deviations // []] | flatten | length),
              cost: {
                outputTokens: ([ ($r.planning.totals.output // 0) ] + [ $r.phases[]?.telemetry.totals.output // 0 ] | add),
                turns:        ([ ($r.planning.totals.turns // 0) ]  + [ $r.phases[]?.telemetry.totals.turns // 0 ]  | add)
              }
            }
        ] | sort_by(.date) | reverse
      ' "${report_files[@]}")
    fi
    if [ "$text_mode" != "1" ]; then
      printf '%s\n' "$rows"
    elif [ "$(jq 'length' <<<"$rows")" -eq 0 ]; then
      echo "No batch has a report yet — reports have existed only since v0.2, so older batches never got one."
    else
      jq -r '
        (["Repo","Batch","Status","Dev.","Date","Cost"] | "| " + join(" | ") + " |"),
        "|---|---|---|---|---|---|",
        (.[] | [
            (.repo | split("/") | last),
            .batch,
            (if .status == "RED" or .status == "MIXED" then "**" + .status + "**" else .status end),
            (.deviations | tostring),
            .date,
            (if .cost.outputTokens == 0 then "–" else (((.cost.outputTokens / 1000) | round | tostring) + "k") end)
          ] | "| " + join(" | ") + " |")
      ' <<<"$rows"
      while IFS= read -r row; do
        rrepo=$(jq -r '.repo' <<<"$row")
        rbatch=$(jq -r '.batch' <<<"$row")
        bpath=$(jq -r --arg repo "$rrepo" --arg batch "$rbatch" \
          '.[] | select(.repo == $repo and .name == $batch) | .path' <<<"$meta")
        printf 'file://%s\n' "$(resolve_html_path "${bpath%/report.json}")"
      done < <(jq -c '.[]' <<<"$rows")
    fi
    ;;
  detail)
    dir="${2:?usage: cfq-report.sh detail <batch-dir>}"
    dir="${dir%/}"
    f="$dir/report.json"
    if [ ! -f "$f" ]; then
      jq -n '{found: false}'
    else
      repo_root="$(repo_root_of "$dir")"
      todos="[]"
      if [ -n "$repo_root" ] && [ -d "$repo_root/.claude/cfq/todo" ]; then
        todos=$(
          shopt -s nullglob
          for t in "$repo_root/.claude/cfq/todo"/*.md; do
            jq -Rn --arg file "$(basename "$t")" --arg title "$(sed -n '1{s/^#\+[[:space:]]*//;p}' "$t")" \
              '{file: $file, title: $title}'
          done | jq -s -c '.'
        )
      fi
      jq -c --argjson todos "$todos" "$outcome_def"'
        def bound_lines(s; n):
          (s // "") as $s
          | ($s | split("\n")) as $l
          | if ($l | length) <= (2 * n) then $s
            else (($l[0:n] + ["…"] + $l[-n:]) | join("\n"))
            end;
        {
          found: true,
          batch: .batch,
          repo: .repo,
          started: .started,
          status: outcome,
          deviationsTotal: ([.phases[]?.deviations // []] | flatten | length),
          cost: {
            outputTokens: ([ (.planning.totals.output // 0) ] + [ .phases[]?.telemetry.totals.output // 0 ] | add),
            turns:        ([ (.planning.totals.turns // 0) ]  + [ .phases[]?.telemetry.totals.turns // 0 ]  | add)
          },
          phases: [ .phases[] | {
            phase, status, summary: (.summary // ""),
            deviations: (.deviations // []),
            errors: (.errors // []),
            verification: bound_lines(.verification; 5),
            commit: (.commit // ""),
            telemetry: (.telemetry // null)
          } ],
          todos: $todos
        }
      ' "$f"
    fi
    ;;
  *)
    echo "usage: cfq-report.sh append <batch-dir> <phase-json> | security <batch-dir> <security-json> | set-commit <batch-dir> <phase-slug> <sha> | last-failure <batch-dir> <phase-slug> | summary <batch-dir> | html <batch-dir> | index [--repo <substr>] [--batch <substr>] [--any <substr>] [--text] | detail <batch-dir>" >&2
    exit 1
    ;;
esac
