#!/usr/bin/env bash
# Builds the reviewed repo (feature/discounts checked out) plus the round-1 council output in
# council-out/, which is kept out of git so the working tree starts clean.
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
cp -R "$src/council-out" .
echo "council-out/" >> .git/info/exclude
