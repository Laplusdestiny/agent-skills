#!/usr/bin/env bash
set -eu
cp -R "$(dirname "$0")/files/base/." .
git init -q -b main
git add -A
git -c user.name=fixture -c user.email=fixture@example.com commit -qm "initial shop with catalog"
