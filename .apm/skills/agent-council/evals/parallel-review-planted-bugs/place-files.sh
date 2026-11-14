#!/usr/bin/env bash
# Builds a git repo: `main` has the base project, `feature/discounts` (checked out) adds the change under review.
set -eu
src="$(dirname "$0")/files"
cp -R "$src/base/." .
git init -q -b main
git add -A
git -c user.name=fixture -c user.email=fixture@example.com commit -qm "initial shop helpers"
git checkout -q -b feature/discounts
cp -R "$src/feature/." .
git add -A
git -c user.name=fixture -c user.email=fixture@example.com commit -qm "feat: add discounts, simplify auth, tidy pagination"
