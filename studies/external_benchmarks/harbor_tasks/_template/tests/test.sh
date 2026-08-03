#!/bin/bash
# harbor-canary GUID <paste>
set -u
cd /tests
python3 /tests/grade.py                              # writes /logs/verifier/reward.json
python3 -m pytest --tb=short /tests/test_outputs.py -rA
