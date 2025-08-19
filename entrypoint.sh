#!/bin/sh
set -e

# Ensure sounds and data directories exist and are writable
mkdir -p /app/sounds /app/data
chown -R app:app /app/sounds /app/data

cmd="$@"
exec su app -c "$cmd"
