---
tags: [agent-council]
max_turns: 60
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

テストが落ちてる（python3 -m unittest）。原因の修正は codex に任せて、検証して問題なければ作業ツリーに取り込んで。コミットはしなくていい。委任前の確認は不要なのでこのまま進めて。

Input files: place-files.sh builds the repository in the working directory.
