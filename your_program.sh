#!/bin/sh
# Convenience launcher, mirroring the CodeCrafters entry point.
# Usage: ./your_program.sh --port 6379 --dir . --dbfilename dump.rdb
exec python3 -m app "$@"
