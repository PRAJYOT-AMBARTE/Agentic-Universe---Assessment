#!/usr/bin/env bash
# Outcome-First Agent Loop Controller runner.
# Contract: ./run.sh <SIM_URL> runs until the scenario finishes.
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
exec python -m controller.main --url "$SIM_URL"
