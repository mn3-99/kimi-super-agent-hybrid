#!/usr/bin/env bash
# Watchdog: keep the unified server alive forever.
cd "$(dirname "$0")"
while true; do
  echo "===== [$(date -Is)] server starting =====" >> server.log
  ./run.sh >> server.log 2>&1
  echo "===== [$(date -Is)] exited ($?), respawning in 3s =====" >> server.log
  sleep 3
done
