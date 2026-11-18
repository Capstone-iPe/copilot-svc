#!/usr/bin/env bash
# Interactive chat against the copilot HTTP API (same feel as python -m copilot.cli).
#
# Default: COPILOT_BASE_URL from the environment or copilot-svc/.env (Render).
# Local override:
#   ./scripts/http-cli.sh http://127.0.0.1:8080
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

BASE="${1:-${COPILOT_BASE_URL:-${BASE:-}}}"
BASE="${BASE%/}"
if [[ -z "$BASE" ]]; then
  echo "Set COPILOT_BASE_URL to the Render copilot URL (or pass it as \$1)." >&2
  echo "Example local: ./scripts/http-cli.sh http://127.0.0.1:8080" >&2
  exit 1
fi

if ! command -v curl >/dev/null || ! command -v python3 >/dev/null; then
  echo "Need curl and python3." >&2
  exit 1
fi

json_get() {
  local key="$1"
  python3 -c 'import json,sys; d=json.load(sys.stdin); v=d.get(sys.argv[1]);
print("" if v is None else v if not isinstance(v, (dict, list)) else json.dumps(v))' "$key"
}

print_turn() {
  python3 -c '
import json, sys
d = json.load(sys.stdin)
msgs = d.get("messages") or []
if msgs:
    for m in msgs:
        if m:
            print(m)
elif d.get("text"):
    print(d["text"])
'
}

echo "copilot HTTP CLI → $BASE" >&2
health="$(curl -sf "$BASE/v1/health" || true)"
if [[ -z "$health" ]]; then
  echo "Cannot reach $BASE/v1/health — is the API running?" >&2
  exit 1
fi

opened="$(curl -sf -X POST "$BASE/v1/conversations")"
CID="$(printf '%s' "$opened" | json_get conversation_id)"
if [[ -z "$CID" ]]; then
  echo "Open failed: $opened" >&2
  exit 1
fi
echo "conversation $CID" >&2
printf '%s' "$opened" | print_turn

while true; do
  if ! IFS= read -r -p "> " line; then
    echo
    break
  fi
  low="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  if [[ -z "$low" ]]; then
    continue
  fi
  if [[ "$low" == "quit" || "$low" == "exit" ]]; then
    break
  fi

  # File-name style lines go to /files; everything else to /messages.
  if [[ "$line" =~ \.(pdf|png|jpe?g|PDF|PNG|JPE?G)$ ]]; then
    body="$(python3 -c 'import json,sys; print(json.dumps({"file": sys.argv[1]}))' "$line")"
    path="files"
  else
    body="$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$line")"
    path="messages"
  fi

  if ! out="$(curl -sf -X POST "$BASE/v1/conversations/$CID/$path" \
      -H 'Content-Type: application/json' \
      -d "$body")"; then
    echo "Request failed." >&2
    continue
  fi
  printf '%s' "$out" | print_turn
done
