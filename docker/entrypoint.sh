#!/usr/bin/env bash
set -euo pipefail

if [[ "${BROWSER_MODE:-}" == "xvfb" ]]; then
  exec xvfb-run -a -s "-screen 0 1920x1080x24" "$@"
fi

exec "$@"
