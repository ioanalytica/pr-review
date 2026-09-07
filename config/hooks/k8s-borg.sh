# pr-review hook for k8s-borg (Helm chart + shell tooling).
#
# Lint: helm lint on the chart, shellcheck (warning and above) on every
# touched shell script.
# Tests: none wired yet; run-tests.sh needs a cluster and is not a unit
# suite. Add a pr_review_test when a hermetic suite exists.

pr_review_lint() {
  local rc=0 sh_files
  if [ -d chart ] && command -v helm >/dev/null; then
    echo "== helm lint chart"
    helm lint chart || rc=1
  fi
  if command -v shellcheck >/dev/null; then
    sh_files="$(grep -E '\.(sh|bash)$' "$CHANGED_FILES" | while read -r f; do [ -f "$f" ] && echo "$f"; done | tr '\n' ' ')"
    if [ -n "$sh_files" ]; then
      echo "== shellcheck $sh_files"
      # shellcheck disable=SC2086
      shellcheck -S warning $sh_files || rc=1
    fi
  fi
  return $rc
}
