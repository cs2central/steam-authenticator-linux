#!/bin/bash
# Steam Authenticator Linux - Launch Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use virtual environment if it exists
if [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    exec "$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/src/main.py" "$@"
else
    exec python3 "$SCRIPT_DIR/src/main.py" "$@"
fi
