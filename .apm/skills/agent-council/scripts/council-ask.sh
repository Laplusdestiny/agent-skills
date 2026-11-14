#!/usr/bin/env bash
# Read-only consultation of Codex CLI and/or Antigravity CLI (agy).
#
# Every selected agent receives the same self-contained prompt (and, for reviews, the same
# pre-generated diff file), runs in parallel in a read-only mode, and writes its answer to
# <out-dir>/<agent>.md. Read-only enforcement lives here, not in the prompt:
#   codex -> `codex exec -s read-only` / `codex exec review -c sandbox_mode="read-only"`
#   agy   -> `agy --mode plan` (headless agy also auto-denies shell commands)
set -uo pipefail

usage() {
  cat <<'EOF'
Usage: council-ask.sh --prompt-file FILE --out-dir DIR [options]

Required:
  --prompt-file FILE   Self-contained prompt. Point at files by path rather than pasting them.
  --out-dir DIR        Directory for answers, logs, and the exact prompt that was sent.

Options:
  --agents LIST        Comma-separated subset of: codex,agy   (default: codex,agy)
  --cwd DIR            Directory the agents inspect (default: current directory)
  --diff-base REF      Review target: everything since merge-base(REF, HEAD), incl. uncommitted
  --uncommitted        Review target: staged + unstaged + untracked changes vs HEAD
  --codex-builtin      With a review target, run Codex's built-in reviewer (`codex exec review`)
                       instead of answering --prompt-file. Good for a general bug hunt; it
                       ignores the prompt, so skip it when the review has a specific focus.
  --image FILE         Attach an image (repeatable). Codex gets `-i`; agy is told the path.
  --timeout SEC        Per-agent wall-clock limit (default: 600)

Environment:
  AGENT_COUNCIL_AGY_MODEL    agy model id (default: first Gemini "-high" model from `agy models`)
  AGENT_COUNCIL_CODEX_MODEL  codex model id (default: codex's configured model)
EOF
}

agents="codex,agy"; prompt_file=""; out_dir=""; cwd="."; diff_base=""; uncommitted=0
codex_builtin=0; timeout_s=600; images=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agents) agents="$2"; shift 2 ;;
    --prompt-file) prompt_file="$2"; shift 2 ;;
    --out-dir) out_dir="$2"; shift 2 ;;
    --cwd) cwd="$2"; shift 2 ;;
    --diff-base) diff_base="$2"; shift 2 ;;
    --uncommitted) uncommitted=1; shift ;;
    --codex-builtin) codex_builtin=1; shift ;;
    --image) images+=("$(realpath "$2")"); shift 2 ;;
    --timeout) timeout_s="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$prompt_file" && -f "$prompt_file" ]] || { echo "--prompt-file is required and must exist" >&2; exit 2; }
[[ -n "$out_dir" ]] || { echo "--out-dir is required" >&2; exit 2; }
[[ -n "$diff_base" && $uncommitted -eq 1 ]] && { echo "use only one of --diff-base / --uncommitted" >&2; exit 2; }

mkdir -p "$out_dir"
out_dir="$(realpath "$out_dir")"
cwd="$(realpath "$cwd")"

# --- Build the shared context: one diff file both reviewers read -----------------------------
diff_file=""
# Build/test byproducts that show up as untracked in repos without a matching .gitignore
# (e.g. after Claude runs the tests). Reviewers would flag them as "committed junk".
generated_re='(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|node_modules|\.venv)/|\.py[co]$|(^|/)\.DS_Store$'
append_untracked() {
  # `git diff` omits untracked files; render them as additions so reviewers see new files too.
  git -C "$cwd" ls-files --others --exclude-standard -z |
    while IFS= read -r -d '' f; do
      if [[ "$f" =~ $generated_re ]]; then
        echo "$f" >> "$out_dir/skipped-untracked.txt"; continue
      fi
      git -C "$cwd" diff --no-index --binary -- /dev/null "$f" 2>/dev/null
    done
}
if [[ -n "$diff_base" || $uncommitted -eq 1 ]]; then
  diff_file="$out_dir/diff.patch"
  rm -f "$out_dir/skipped-untracked.txt"
  if [[ -n "$diff_base" ]]; then
    mb="$(git -C "$cwd" merge-base "$diff_base" HEAD)" || { echo "cannot resolve merge-base of $diff_base" >&2; exit 2; }
    git -C "$cwd" diff --binary "$mb" > "$diff_file"
  else
    git -C "$cwd" diff --binary HEAD > "$diff_file"
  fi
  append_untracked >> "$diff_file"
  if [[ ! -s "$diff_file" ]]; then
    echo "review target is empty: no changes found" >&2
    exit 3
  fi
fi

final_prompt="$out_dir/prompt.sent.md"
{
  cat "$prompt_file"
  echo
  if [[ -n "$diff_file" ]]; then
    echo "---"
    echo "The change under review is in the unified diff at: $diff_file"
    echo "Read that file first. You may open any file under $cwd for surrounding context."
  fi
  if [[ ${#images[@]} -gt 0 ]]; then
    echo "---"
    echo "Images to examine:"
    printf -- '- %s\n' "${images[@]}"
  fi
  echo "---"
  echo "This is a read-only consultation: do not modify any files."
} > "$final_prompt"

# --- Agent runners ---------------------------------------------------------------------------
resolve_agy_model() {
  if [[ -n "${AGENT_COUNCIL_AGY_MODEL:-}" ]]; then echo "$AGENT_COUNCIL_AGY_MODEL"; return; fi
  # Pin a Gemini model on purpose: agy can also serve Claude models, and asking Claude for a
  # "second opinion" from Claude defeats the point of the council.
  local models
  models="$(timeout 60 agy models 2>/dev/null | awk '{print $1}' | grep '^gemini' || true)"
  { grep -- '-high$' <<<"$models" || echo "$models"; } | head -n1
}

run_codex() {
  local model_args=()
  [[ -n "${AGENT_COUNCIL_CODEX_MODEL:-}" ]] && model_args=(-m "$AGENT_COUNCIL_CODEX_MODEL")
  if [[ -n "$diff_file" && $codex_builtin -eq 1 ]]; then
    local target=(--uncommitted)
    [[ -n "$diff_base" ]] && target=(--base "$diff_base")
    # `codex exec review` rejects a PROMPT together with --base/--uncommitted, so no prompt here.
    (cd "$cwd" && timeout "$timeout_s" codex exec review "${target[@]}" "${model_args[@]}" \
      -c 'sandbox_mode="read-only"' --ephemeral -o "$out_dir/codex.md") \
      > "$out_dir/codex.log" 2>&1
  else
    local img_args=()
    for img in "${images[@]}"; do img_args+=(-i "$img"); done
    timeout "$timeout_s" codex exec -s read-only --ephemeral --skip-git-repo-check -C "$cwd" \
      "${model_args[@]}" "${img_args[@]}" -o "$out_dir/codex.md" - < "$final_prompt" \
      > "$out_dir/codex.log" 2>&1
  fi
}

has_text() { grep -q '[^[:space:]]' "$1" 2>/dev/null; }

run_agy() {
  local model add_dirs=(--add-dir "$out_dir") rc attempt prompt
  model="$(resolve_agy_model)"
  echo "$model" > "$out_dir/agy.model"
  for img in "${images[@]}"; do add_dirs+=(--add-dir "$(dirname "$img")"); done
  # Headless agy auto-denies shell commands, and a denied command ends the turn with an empty
  # answer. Say so up front, and retry once with a sharper note if it happens anyway.
  prompt="$(cat "$final_prompt")
Shell commands are not available to you in this session; any attempt is denied and ends your
turn without an answer. Work only by reading files, then answer."
  for attempt in 1 2; do
    # The prompt must be attached with `-p=`; `-p -` is taken literally, not read from stdin.
    (cd "$cwd" && timeout "$timeout_s" agy --mode plan ${model:+--model "$model"} \
      --output-format json "${add_dirs[@]}" -p="$prompt") \
      > "$out_dir/agy.json" 2>> "$out_dir/agy.log"
    rc=$?
    jq -r '.response // empty' "$out_dir/agy.json" > "$out_dir/agy.md" 2>/dev/null
    if [[ $rc -eq 0 ]] && ! has_text "$out_dir/agy.md" &&
       jq -e '.denied_actions | length > 0' "$out_dir/agy.json" >/dev/null 2>&1; then
      echo "note: attempt $attempt ended on a denied tool call: $(jq -c '.denied_actions' "$out_dir/agy.json")" >> "$out_dir/agy.log"
      prompt="$prompt
Your previous attempt tried to run a shell command and was stopped. Do not run any command:
read the files named above directly and give your answer."
      continue
    fi
    break
  done
  [[ $rc -eq 0 ]] && has_text "$out_dir/agy.md"
}

# --- Run in parallel and report --------------------------------------------------------------
declare -A pids
IFS=',' read -r -a selected <<<"$agents"
for a in "${selected[@]}"; do
  case "$a" in
    codex|agy)
      if ! command -v "$a" >/dev/null 2>&1; then
        echo "$a: unavailable (not on PATH)" > "$out_dir/$a.status"; continue
      fi
      "run_$a" & pids[$a]=$! ;;
    *) echo "unknown agent: $a" >&2; exit 2 ;;
  esac
done

any_ok=1
for a in "${selected[@]}"; do
  if [[ -n "${pids[$a]:-}" ]]; then
    wait "${pids[$a]}"; rc=$?
    if [[ $rc -eq 0 ]] && has_text "$out_dir/$a.md"; then
      echo "$a: ok -> $out_dir/$a.md" > "$out_dir/$a.status"; any_ok=0
    elif [[ $rc -eq 124 ]]; then
      echo "$a: timed out after ${timeout_s}s (log: $out_dir/$a.log)" > "$out_dir/$a.status"
    else
      echo "$a: failed (exit $rc, log: $out_dir/$a.log)" > "$out_dir/$a.status"
    fi
  fi
  cat "$out_dir/$a.status"
done
[[ -n "$diff_file" ]] && echo "diff: $diff_file"
echo "prompt sent: $final_prompt"
exit $any_ok
