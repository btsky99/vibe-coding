#!/data/data/com.termux/files/usr/bin/bash
#
# FILE: scripts/mobile_agent_bus_boot.sh
# DESCRIPTION: Termux:Boot launcher for the Note20 APIS1 central bus.
#
# REVISION HISTORY:
# - 2026-07-27 Codex: Added single-instance startup and wake-lock handling.

BUS_HOME="$HOME/apis-bus"
BUS_SCRIPT="$BUS_HOME/mobile_agent_bus.py"
BUS_LOG="$BUS_HOME/agent_bus.log"

mkdir -p "$BUS_HOME"
termux-wake-lock 2>/dev/null || true

if pgrep -f "mobile_agent_bus.py serve" >/dev/null 2>&1; then
  exit 0
fi

nohup env PYTHONUTF8=1 python "$BUS_SCRIPT" serve \
  >>"$BUS_LOG" 2>&1 </dev/null &
