#!/usr/bin/env bash
# Implementation reports per batch. The report lives in the batch directory and travels with it.
# Usage: cfq-report.sh append <batch-dir> <phase-json>
#        cfq-report.sh security <batch-dir> <security-json>
#        cfq-report.sh set-commit <batch-dir> <phase-slug> <sha>
#        cfq-report.sh last-failure <batch-dir> <phase-slug>
#        cfq-report.sh summary <batch-dir>
#        cfq-report.sh html <batch-dir>
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-report.sh: jq is required" >&2; exit 1; }

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
    f="$dir/report.json"
    ensure_report "$dir"
    jq --argjson p "$phase" '.phases += [$p]' "$f" >"$f.tmp" && mv "$f.tmp" "$f"
    # Telemetry attaches to the entry just written. Never fatal: a missing transcript must not
    # cost the phase its report.
    "$(dirname "${BASH_SOURCE[0]}")/cfq-telemetry.sh" record "$dir" phase \
      "$(printf '%s' "$phase" | jq -r '.phase // ""')" || true
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
    jq --arg p "$phase_slug" --arg c "$sha" '
      (.phases | to_entries | map(select(.value.phase == $p)) | last.key) as $i
      | if $i == null then . else .phases[$i].commit = $c end
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
    f="$dir/report.json"
    [ -f "$f" ] || { echo "cfq-report.sh: no report.json in $dir" >&2; exit 1; }
    out="$dir/report.html"
    jq -r '
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
        "<section class=\"phase " + .status + "\">" +
        "<h3><span class=\"badge " + .status + "\">" + (.status | ascii_upcase | @html) + "</span> " +
        (.phase | esc) + "</h3>" +
        "<p>" + (.summary | esc) + "</p>" +
        telemetry_html +
        ((.deviations // []) | section_list("Deviations")) +
        ((.errors // []) | section_list("Errors")) +
        (if (.verification // "") != "" then "<p class=\"verification\"><code>" + (.verification | esc) + "</code></p>" else "" end) +
        (if (.commit // "") != "" then "<p class=\"commit\">Commit: <code>" + (.commit | esc) + "</code></p>" else "" end) +
        "</section>";
      "<!doctype html><html><head><meta charset=\"utf-8\"><title>" + (.batch | esc) + " report</title><style>" +
      "body{font-family:system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fff}" +
      "@media (prefers-color-scheme: dark){body{color:#e8e8e8;background:#1a1a1a}code{background:#2a2a2a}}" +
      ".meta,.summary{color:#666}section.phase{border-left:4px solid #999;padding:0.5rem 1rem;margin:1rem 0}" +
      "section.phase.green{border-color:#2a8f4a}section.phase.red{border-color:#c0392b}" +
      ".badge{display:inline-block;padding:0.1rem 0.5rem;border-radius:0.3rem;font-size:0.8rem;color:#fff}" +
      ".badge.green{background:#2a8f4a}.badge.red{background:#c0392b}" +
      "code{background:#f0f0f0;padding:0.1rem 0.3rem;border-radius:0.2rem}" +
      ".telemetry{color:#666;font-size:0.85rem}.kv{margin-right:0.4rem}" +
      "</style></head><body>" +
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
    ;;
  *)
    echo "usage: cfq-report.sh append <batch-dir> <phase-json> | security <batch-dir> <security-json> | set-commit <batch-dir> <phase-slug> <sha> | last-failure <batch-dir> <phase-slug> | summary <batch-dir> | html <batch-dir>" >&2
    exit 1
    ;;
esac
