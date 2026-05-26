#!/usr/bin/env bash
set -euo pipefail

if [[ "${BROWSER_MODE:-}" == "xvfb" ]]; then
  export DISPLAY="${DISPLAY:-:99}"
  server_num="${DISPLAY#:}"
  Xvfb "$DISPLAY" -screen 0 1920x1080x24 -nolisten tcp &
  xvfb_pid="$!"

  cleanup() {
    kill "$xvfb_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
  }
  trap cleanup EXIT

  for _ in $(seq 1 50); do
    if [[ -S "/tmp/.X11-unix/X${server_num}" ]]; then
      break
    fi
    sleep 0.1
  done

  "$@"
  status="$?"
  cleanup
  exit "$status"
fi

exec "$@"
