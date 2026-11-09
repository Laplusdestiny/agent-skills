#!/usr/bin/env bash
# Builds a git repo on `main` whose pagination tests fail (off-by-one in shop/pagination.py).
set -eu
cp -R "$(dirname "$0")/files/base/." .
git init -q -b main
git add -A
git -c user.name=fixture -c user.email=fixture@example.com commit -qm "initial shop helpers"
