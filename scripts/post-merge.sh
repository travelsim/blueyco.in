#!/bin/bash
set -e

# Pure Python project — no build step or migrations needed.
# Verify the server entrypoint exists and is importable.
python3 -c "import py_compile, sys; py_compile.compile('server.py', doraise=True)"

echo "Post-merge setup OK"
