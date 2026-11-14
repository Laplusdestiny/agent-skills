---
tags: [agent-council]
max_turns: 60
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

商品ページが遅いので shop/catalog.py の get_product にキャッシュを入れたい。Redis を立てるか、プロセス内の LRU キャッシュで済ますか迷ってる。前提は DEPLOYMENT.md に書いた。codex と agy の意見も聞いたうえでおすすめを教えて。

Input files: place-files.sh builds the repository in the working directory.
