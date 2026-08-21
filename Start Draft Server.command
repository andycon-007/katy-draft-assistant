#!/bin/bash
# Double-click this, or add it to System Settings > General > Login Items,
# to start the draft server.
#
# It restarts itself if the server crashes, which a plain Login Item would not —
# a crash mid-draft is exactly when you would be least able to fix it by hand.

cd "$(dirname "$0")" || exit 1

PORT="${PORT:-8000}"
LOG="/tmp/draft_server.log"

echo "Fantasy Draft Assistant"
echo "======================="
echo

# Refuse to start a second copy — two servers on one port means one silently
# fails and you cannot tell which one the iPad is talking to.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Something is already listening on port $PORT."
  echo "The server is probably already running. Open:"
  echo "   http://andys-mac-mini:$PORT"
  echo
  read -r -p "Press Return to close this window."
  exit 0
fi

if [ ! -x .venv/bin/python ]; then
  echo "No virtualenv found at .venv/"
  echo "Run:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  echo
  read -r -p "Press Return to close this window."
  exit 1
fi

echo "Open this on the iPad (Tailscale must be on):"
echo "   http://andys-mac-mini:$PORT"
echo
echo "Logging to $LOG"
echo "Leave this window open. Close it to stop the server."
echo

# Restart loop. A clean exit (Ctrl-C) stops; a crash restarts after a moment.
while true; do
  MANUAL_MODE=1 .venv/bin/python -m uvicorn src.server:app \
    --host 0.0.0.0 --port "$PORT" >>"$LOG" 2>&1
  code=$?
  if [ $code -eq 0 ] || [ $code -eq 130 ]; then
    echo "Server stopped."
    break
  fi
  echo "Server exited unexpectedly (code $code). Restarting in 3s…"
  sleep 3
done

read -r -p "Press Return to close this window."
