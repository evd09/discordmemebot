#!/bin/sh
set -e

# Ensure sounds directory exists and is writable
mkdir -p /app/sounds
chown -R app:app /app/sounds

cmd="$@"
exec su app -c "$cmd"
