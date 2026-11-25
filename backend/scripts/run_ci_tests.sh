#!/bin/sh
# Run the backend test stages the way CI does, against the dedicated test database.
# See run_ci_tests.ps1 for the rationale. Start the database first:
#   docker compose -f docker-compose.test.yml up -d
#
# Usage: sh backend/scripts/run_ci_tests.sh [all|lint|unit|integration] [workers]

STAGE="${1:-all}"
WORKERS="${2:-4}"
cd "$(dirname "$0")/.." || exit 1

export DATABASE_URL="postgresql+psycopg://test:test@localhost:5433/test_batchivo"
export ENVIRONMENT=test
FAILED=""

run() {
  name="$1"; shift
  echo "=== $name ==="
  "$@" || FAILED="$FAILED $name"
}

case "$STAGE" in all|lint)
  run ruff-check poetry run ruff check .
  run ruff-format poetry run ruff format --check . ;;
esac
case "$STAGE" in all|unit)
  run unit poetry run pytest tests/unit/ --tb=short -q -p no:cacheprovider -n "$WORKERS" --dist worksteal ;;
esac
case "$STAGE" in all|integration)
  run integration poetry run pytest tests/ --ignore=tests/unit/ --tb=short -q -p no:cacheprovider -n "$WORKERS" --dist worksteal ;;
esac

if [ -n "$FAILED" ]; then echo "FAILED:$FAILED"; exit 1; fi
echo "All stages passed"
