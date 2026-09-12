#!/bin/bash
# Rebuild the Pyodide harness and drop it where the preview server serves from.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCROOT="${ARTHA_DOCROOT:?set ARTHA_DOCROOT to the preview server docroot}"
ARTHA_HARNESS_OUT="$DOCROOT/index.html" "$ROOT/tools/mkharness.sh" "${1:-tools/harness_main.py}"
