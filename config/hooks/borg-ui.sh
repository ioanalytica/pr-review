# pr-review hook for borg-ui (backend: FastAPI + pytest, frontend: Vite + vitest).
#
# Mirrors .github/workflows/tests.yml: ruff check/format, pytest tests/unit,
# prettier/tsc/oxlint/locale parity, vitest. Each layer runs only when the
# diff touches its side of the tree. Runs with cwd=$SRC (a clean export of
# HEAD), so nothing here touches the real checkout.

_bui_touches() { grep -q -E "$1" "$CHANGED_FILES"; }
_bui_backend_changed()  { _bui_touches '^(app/|tests/|alembic|pyproject\.toml|requirements\.txt|ruff\.toml|pytest\.ini)'; }
_bui_frontend_changed() { _bui_touches '^frontend/'; }

# One cached venv per requirements.txt content, created on first use.
_bui_venv() {
  local key venv
  key="$(shasum -a 256 requirements.txt | cut -c1-12)"
  venv="$CACHE/venv/borg-ui-$key"
  if [ ! -x "$venv/bin/python" ]; then
    echo "== creating venv $venv (first run for this requirements.txt)" >&2
    python3 -m venv "$venv"
    "$venv/bin/pip" install -q --upgrade pip
    "$venv/bin/pip" install -q -r requirements.txt
  fi
  echo "$venv"
}

# Frontend deps: reuse the checkout's node_modules unless the lockfile moved.
_bui_node_modules() {
  if [ -d "$SRC/frontend/node_modules" ]; then return 0; fi
  if [ -d "$REPO/frontend/node_modules" ] && cmp -s "$REPO/frontend/package-lock.json" "$SRC/frontend/package-lock.json"; then
    ln -s "$REPO/frontend/node_modules" "$SRC/frontend/node_modules"
    echo "== frontend/node_modules linked from checkout (lockfile unchanged)"
  else
    echo "== frontend/package-lock.json changed, running npm ci"
    (cd "$SRC/frontend" && npm ci --no-audit --no-fund --silent)
  fi
}

pr_review_lint() {
  local venv rc=0
  if _bui_backend_changed; then
    venv="$(_bui_venv)"
    echo "== ruff check app tests";        "$venv/bin/ruff" check app tests        || rc=1
    echo "== ruff format --check app tests"; "$venv/bin/ruff" format --check app tests || rc=1
  else
    echo "(backend untouched, ruff skipped)"
  fi
  if _bui_frontend_changed; then
    _bui_node_modules
    ( cd frontend
      echo "== npm run format:check";  npm run -s format:check  || exit 1
      echo "== npm run typecheck";     npm run -s typecheck     || exit 1
      echo "== npm run lint";          npm run -s lint          || exit 1
      echo "== npm run check:locales"; npm run -s check:locales || exit 1
    ) || rc=1
  else
    echo "(frontend untouched, frontend gates skipped)"
  fi
  return $rc
}

pr_review_test() {
  local venv rc=0 scope
  if _bui_backend_changed; then
    venv="$(_bui_venv)"
    mkdir -p data logs /tmp/borg-ui-tests
    if [ "${QUICK:-0}" -eq 1 ]; then
      scope="$(grep -E '^tests/unit/.*test_.*\.py$' "$CHANGED_FILES" | while read -r f; do [ -f "$f" ] && echo "$f"; done | tr '\n' ' ')"
      if [ -z "$scope" ]; then
        echo "(quick: no touched unit test files, backend tests skipped)"
      else
        echo "== pytest (quick, touched files only): $scope"
        # shellcheck disable=SC2086
        "$venv/bin/python" -m pytest $scope -q -p no:cacheprovider -o addopts='-ra' || rc=1
      fi
    else
      echo "== pytest tests/unit"
      "$venv/bin/python" -m pytest tests/unit -q -p no:cacheprovider -o addopts='-ra' || rc=1
    fi
  else
    echo "(backend untouched, pytest skipped)"
  fi
  if _bui_frontend_changed && [ "${QUICK:-0}" -eq 0 ]; then
    _bui_node_modules
    echo "== vitest run (Node 22, CI parity)"
    ( cd frontend && npm exec --yes --package=node@22 -- npm run -s test -- --run ) || rc=1
  elif _bui_frontend_changed; then
    echo "(quick: vitest skipped)"
  else
    echo "(frontend untouched, vitest skipped)"
  fi
  return $rc
}
