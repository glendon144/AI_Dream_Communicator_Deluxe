#!/usr/bin/env bash
set -euo pipefail
python3 -m py_compile app.py webmcp_client.py test_client.py
python3 test_client.py
