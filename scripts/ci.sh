set -euo pipefail

cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME="localpay-ci-$(openssl rand -hex 6)"
export LOCALPAY_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export LOCALPAY_ADMIN_TOKEN="$(openssl rand -hex 32)"
export LOCALPAY_WEBHOOK_ENCRYPTION_KEY="$(python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')"
export LOCALPAY_RECEIVER_SECRET="$(openssl rand -hex 32)"
export LOCALPAY_VERIFICATION_TOKEN="$(openssl rand -hex 32)"
export LOCALPAY_API_PORT="${LOCALPAY_CI_API_PORT:-8000}"
export LOCALPAY_DASHBOARD_PORT="${LOCALPAY_CI_DASHBOARD_PORT:-3000}"
export LOCALPAY_API_URL="http://127.0.0.1:$LOCALPAY_API_PORT"
export LOCALPAY_E2E_API_URL="$LOCALPAY_API_URL"
export LOCALPAY_E2E_DASHBOARD_URL="http://127.0.0.1:$LOCALPAY_DASHBOARD_PORT"
export LOCALPAY_E2E_TOKEN="$LOCALPAY_ADMIN_TOKEN"
unset NO_COLOR
if [ "${GITHUB_ACTIONS:-}" = true ]; then
  printf '::add-mask::%s\n' "$LOCALPAY_ADMIN_TOKEN" "$LOCALPAY_WEBHOOK_ENCRYPTION_KEY" "$LOCALPAY_POSTGRES_PASSWORD" "$LOCALPAY_RECEIVER_SECRET" "$LOCALPAY_VERIFICATION_TOKEN"
fi

results="${LOCALPAY_CI_RESULTS:-.localpay-ci}"
mkdir -p "$results"
compose=(docker compose -f compose.yaml -f infra/ci.compose.yaml)

cleanup() {
  local code="$?"
  if [ "$code" -ne 0 ]; then
    "${compose[@]}" ps --all >"$results/compose-status.txt" 2>&1 || true
  fi
  if "${compose[@]}" down --volumes --remove-orphans >"$results/cleanup.txt" 2>&1; then
    exit "$code"
  fi
  exit 1
}
trap cleanup EXIT

apps/api/.venv/bin/ruff check apps/api packages/cli examples scripts
apps/api/.venv/bin/ruff format --check apps/api packages/cli examples scripts
(cd apps/api && .venv/bin/mypy)
apps/api/.venv/bin/mypy --strict packages/cli/src
packages/cli/.venv/bin/python -m unittest discover -s packages/cli/tests
npm run lint --prefix apps/dashboard
npm run typecheck --prefix apps/dashboard

"${compose[@]}" up --build --detach --wait receiver
receiver="$("${compose[@]}" ps --quiet receiver)"
receiver_ip="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$receiver")"
export LOCALPAY_WEBHOOK_TARGETS="{\"http://receiver:9001\":\"$receiver_ip\"}"
"${compose[@]}" config --quiet
"${compose[@]}" up --build --detach --wait --wait-timeout 180
"${compose[@]}" exec -T api alembic check
"${compose[@]}" run --no-deps --build --rm verify pytest -W error | tee "$results/backend.txt"
python3 examples/verify_integrations.py | tee "$results/examples.txt"
python3 scripts/ci_suites.py "$results"
"${compose[@]}" stop reliability-worker
python3 scripts/ci_suites.py "$results" --verify-blocked
"${compose[@]}" start reliability-worker
npm test --prefix apps/dashboard | tee "$results/browser.txt"
if [ "${LOCALPAY_EXTENDED_VERIFY:-0}" = 1 ]; then
  python3 scripts/resilience.py "$results/resilience.json"
  python3 scripts/benchmark.py "$results/benchmark.json"
fi
