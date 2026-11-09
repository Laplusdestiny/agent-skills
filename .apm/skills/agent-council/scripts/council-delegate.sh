#!/usr/bin/env bash
# Delegate an implementation task to Codex CLI or Antigravity CLI (agy) inside a dedicated
# git worktree, then hand back a patch for Claude to review and integrate.
#
# The delegate never touches the user's working tree and never commits: it edits files in
# its own worktree, and this script stages that worktree only to produce <out-dir>/changes.patch.
# Integrating the patch (or discarding it) stays with Claude and the user.
set -uo pipefail

usage() {
  cat <<'EOF'
Usage: council-delegate.sh --agent codex|agy --task-file FILE --name SLUG [options]

Required:
  --agent codex|agy    Who implements the task
  --task-file FILE     Self-contained task brief (goal, files in scope, constraints, done-criteria)
  --name SLUG          Short kebab-case id; names the worktree and the branch council/<agent>/<SLUG>

Options:
  --repo DIR           Repository to branch from (default: current directory)
  --base REF           Commit to start from (default: HEAD). Uncommitted work is NOT carried over.
  --reuse              Run again in an existing worktree for SLUG (follow-up round with feedback)
  --out-dir DIR        Logs, summary, and patch (default: $TMPDIR/agent-council/<repo>/<SLUG>)
  --timeout SEC        Wall-clock limit (default: 1800)

Environment:
  AGENT_COUNCIL_WORKTREE_ROOT  Parent dir for worktrees (default: <repo>/../.agent-council-worktrees)
  AGENT_COUNCIL_AGY_MODEL      agy model id (default: first Gemini "-high" model from `agy models`)
  AGENT_COUNCIL_CODEX_MODEL    codex model id (default: codex's configured model)
EOF
}

agent=""; task_file=""; name=""; repo="."; base="HEAD"; reuse=0; out_dir=""; timeout_s=1800

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) agent="$2"; shift 2 ;;
    --task-file) task_file="$2"; shift 2 ;;
    --name) name="$2"; shift 2 ;;
    --repo) repo="$2"; shift 2 ;;
    --base) base="$2"; shift 2 ;;
    --reuse) reuse=1; shift ;;
    --out-dir) out_dir="$2"; shift 2 ;;
    --timeout) timeout_s="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$agent" == codex || "$agent" == agy ]] || { echo "--agent must be codex or agy" >&2; exit 2; }
[[ -n "$task_file" && -f "$task_file" ]] || { echo "--task-file is required and must exist" >&2; exit 2; }
[[ "$name" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "--name must be kebab-case" >&2; exit 2; }
command -v "$agent" >/dev/null 2>&1 || { echo "$agent: unavailable (not on PATH)" >&2; exit 4; }

top="$(git -C "$repo" rev-parse --show-toplevel)" || { echo "not a git repository: $repo" >&2; exit 2; }
repo_name="$(basename "$top")"
wt_root="${AGENT_COUNCIL_WORKTREE_ROOT:-$(dirname "$top")/.agent-council-worktrees}/$repo_name"
wt="$wt_root/$name"
branch="council/$agent/$name"
out_dir="${out_dir:-${TMPDIR:-/tmp}/agent-council/$repo_name/$name}"
mkdir -p "$out_dir"
out_dir="$(realpath "$out_dir")"

# --- Worktree ---------------------------------------------------------------------------------
if [[ $reuse -eq 1 ]]; then
  [[ -d "$wt" ]] || { echo "--reuse given but no worktree at $wt" >&2; exit 2; }
  base_sha="$(cat "$out_dir/base.sha" 2>/dev/null || git -C "$wt" merge-base HEAD "$base")"
else
  [[ -e "$wt" ]] && { echo "worktree already exists: $wt (use --reuse for a follow-up round)" >&2; exit 2; }
  base_sha="$(git -C "$top" rev-parse --verify "$base^{commit}")" || { echo "bad --base: $base" >&2; exit 2; }
  if [[ -n "$(git -C "$top" status --porcelain)" ]]; then
    echo "warning: $top has uncommitted changes; the delegate starts from $base and will not see them" >&2
  fi
  mkdir -p "$wt_root"
  git -C "$top" worktree add -q -b "$branch" "$wt" "$base_sha" || exit 2
  echo "$base_sha" > "$out_dir/base.sha"
fi

prompt="$out_dir/prompt.sent.md"
{
  cat "$task_file"
  echo
  echo "---"
  echo "Ground rules for this delegated task:"
  echo "- Your working directory is a dedicated git worktree: $wt. Change files only inside it."
  echo "- Do not run git commit, git push, create branches, or open pull requests; leave changes uncommitted."
  echo "- Stay within the scope described above. If something outside it seems necessary, say so in your summary instead of doing it."
  echo "- Finish with a short summary: files changed, what you verified (and how), and anything left unverified or uncertain."
  if [[ "$agent" == agy ]]; then
    # Headless agy auto-denies shell commands and a denied call ends the turn, so keep it on edits.
    echo "- Shell commands are not available in this session (they are denied and end your turn). Read and edit files only; do not try to run tests or builds — they will be run separately."
  fi
} > "$prompt"

# --- Run the delegate -------------------------------------------------------------------------
started="$(date +%s)"
if [[ "$agent" == codex ]]; then
  model_args=()
  [[ -n "${AGENT_COUNCIL_CODEX_MODEL:-}" ]] && model_args=(-m "$AGENT_COUNCIL_CODEX_MODEL")
  timeout "$timeout_s" codex exec -s workspace-write -C "$wt" "${model_args[@]}" \
    -o "$out_dir/summary.md" - < "$prompt" > "$out_dir/codex.log" 2>&1
  rc=$?
else
  model="${AGENT_COUNCIL_AGY_MODEL:-}"
  if [[ -z "$model" ]]; then
    models="$(timeout 60 agy models 2>/dev/null | awk '{print $1}' | grep '^gemini' || true)"
    model="$( { grep -- '-high$' <<<"$models" || echo "$models"; } | head -n1)"
  fi
  # accept-edits: file edits are auto-approved; shell commands are still auto-denied in headless
  # mode, so agy cannot run tests here — Claude runs them during review.
  (cd "$wt" && timeout "$timeout_s" agy --mode accept-edits ${model:+--model "$model"} \
    --output-format json -p="$(cat "$prompt")") > "$out_dir/agy.json" 2> "$out_dir/agy.log"
  rc=$?
  jq -r '.response // empty' "$out_dir/agy.json" > "$out_dir/summary.md" 2>/dev/null
  echo "$model" > "$out_dir/agy.model"
fi
elapsed=$(( $(date +%s) - started ))

# --- Collect the result -----------------------------------------------------------------------
commits="$(git -C "$wt" rev-list --count "$base_sha"..HEAD)"
git -C "$wt" add -A
# Leave build/test byproducts (bytecode, caches) out of the patch; repos without a matching
# .gitignore would otherwise hand them to the user's tree along with the real change.
generated_re='(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|node_modules|\.venv)/|\.py[co]$|(^|/)\.DS_Store$'
git -C "$wt" diff --cached --name-only --diff-filter=A "$base_sha" | grep -E "$generated_re" > "$out_dir/skipped-generated.txt"
if [[ -s "$out_dir/skipped-generated.txt" ]]; then
  git -C "$wt" rm -q --cached --pathspec-from-file="$out_dir/skipped-generated.txt"
fi
git -C "$wt" diff --cached --binary "$base_sha" > "$out_dir/changes.patch"

echo "agent:     $agent (exit $rc, ${elapsed}s$([[ $rc -eq 124 ]] && echo ', TIMED OUT'))"
echo "worktree:  $wt"
echo "branch:    $branch (base $base_sha)"
echo "summary:   $out_dir/summary.md (the delegate's own account — verify against the patch)"
echo "patch:     $out_dir/changes.patch"
[[ "$commits" -gt 0 ]] && echo "WARNING:   the delegate created $commits commit(s) despite instructions; they are included in the patch"
[[ -s "$out_dir/skipped-generated.txt" ]] && echo "skipped:   $(wc -l < "$out_dir/skipped-generated.txt") generated file(s) left out of the patch (list: $out_dir/skipped-generated.txt)"
echo "--- diff stat ---"
git -C "$wt" diff --cached --stat "$base_sha"
[[ -s "$out_dir/changes.patch" ]] || { echo "(no changes produced)"; exit $(( rc == 0 ? 5 : 1 )); }
exit $(( rc == 0 ? 0 : 1 ))
