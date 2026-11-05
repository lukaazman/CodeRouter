#!/bin/sh
# Run from anywhere; relative paths such as -C . stay relative to the caller.
exec python3 "$(dirname "$0")/CodeRouter.py" "$@"
