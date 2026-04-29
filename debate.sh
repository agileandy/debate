#!/usr/bin/env bash
#
# debate.sh - Programmable AI agent demo: parallel personas + synthesis.
#
# Asks the user's question in parallel to three "personas" of the same model
# (de Bono White / Yellow / Black hats), waits for all three to finish, then
# pipes the combined output into a fourth call that synthesises a balanced
# answer.
#
# Usage:
#   ./debate.sh "Should we adopt Rust for our core service?"
#   echo "Should we ..." | ./debate.sh
#
# Requirements: claude CLI on PATH (any auth method works).

set -euo pipefail

# --- Colors ---------------------------------------------------------------
B=$'\033[1m'   # bold
C=$'\033[36m'  # cyan
G=$'\033[32m'  # green
Y=$'\033[33m'  # yellow
D=$'\033[2m'   # dim
R=$'\033[0m'   # reset

banner() {
    local label="$1"
    printf "\n${C}${B}═══ %s ═══${R}\n\n" "$label"
}

# --- Help -----------------------------------------------------------------
case "${1:-}" in
    -h|--help|help)
        cat <<'EOF'
debate.sh - Programmable AI agent demo: parallel personas + synthesis.

Asks the question in parallel to three "personas" of the same model
(de Bono White / Yellow / Black hats), waits for all three to finish,
then pipes the combined output into a fourth call that synthesises a
balanced answer.

Usage:
  debate.sh "<question>"
  echo "<question>" | debate.sh
  debate.sh -h | --help | help     Show this message

Models:
  Personas:  haiku
  Synthesis: sonnet

Requirements: claude CLI on PATH (any auth method works).
EOF
        exit 0
        ;;
esac

# --- Input ----------------------------------------------------------------
if [[ $# -gt 0 ]]; then
    QUESTION="$*"
else
    QUESTION="$(cat)"
fi

if [[ -z "${QUESTION// }" ]]; then
    echo "usage: $0 \"<question>\"   (or pipe via stdin)" >&2
    exit 1
fi

# --- Setup ----------------------------------------------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PERSONA_MODEL="haiku"     # cheap + fast for the parallel leg
SYNTH_MODEL="sonnet"      # smarter for the synthesis leg

ask_persona() {
    local name="$1" persona_prompt="$2"
    claude -p --tools "" --setting-sources "" --model "$PERSONA_MODEL" \
        --system-prompt "$persona_prompt" \
        "$QUESTION" > "$TMP/$name.txt" 2> "$TMP/$name.err"
}

# --- Show the question ---------------------------------------------------
banner "QUESTION"
printf "%s\n" "$QUESTION"

# --- Fan out: three personas in parallel ----------------------------------
banner "FAN-OUT: 3 personas calling ${PERSONA_MODEL} in parallel"

START=$SECONDS

ask_persona "white" \
    "You are the WHITE HAT (Edward de Bono). Respond with FACTS, DATA, and EVIDENCE only. No opinions, no judgements. Be concise (<150 words)." &
WHITE_PID=$!
printf "${D}  → White Hat  (facts)     spawned as PID ${WHITE_PID}${R}\n"

ask_persona "yellow" \
    "You are the YELLOW HAT (Edward de Bono). Respond with BENEFITS, OPPORTUNITIES, and OPTIMISTIC angles only. Be concise (<150 words)." &
YELLOW_PID=$!
printf "${D}  → Yellow Hat (benefits)  spawned as PID ${YELLOW_PID}${R}\n"

ask_persona "black" \
    "You are the BLACK HAT (Edward de Bono). Respond with RISKS, WEAKNESSES, and CRITICAL concerns only. Be concise (<150 words)." &
BLACK_PID=$!
printf "${D}  → Black Hat  (risks)     spawned as PID ${BLACK_PID}${R}\n"

printf "${Y}  ...waiting for all three to return...${R}\n"
wait
ELAPSED=$((SECONDS - START))
printf "${G}  ✓ all three returned in ${ELAPSED}s${R}\n"

# --- Show each persona's output -------------------------------------------
banner "WHITE HAT — facts"
cat "$TMP/white.txt"

banner "YELLOW HAT — benefits"
cat "$TMP/yellow.txt"

banner "BLACK HAT — risks"
cat "$TMP/black.txt"

# --- Fan in: pipe combined context into the synthesizer -------------------
banner "FAN-IN: synthesising via ${SYNTH_MODEL}"
printf "${Y}  ...combining the 3 perspectives into one balanced answer...${R}\n"

START=$SECONDS
{
    echo "Question from user:"
    echo "$QUESTION"
    echo
    echo "=== WHITE HAT (facts) ==="
    cat "$TMP/white.txt"
    echo
    echo "=== YELLOW HAT (benefits) ==="
    cat "$TMP/yellow.txt"
    echo
    echo "=== BLACK HAT (risks) ==="
    cat "$TMP/black.txt"
} | claude -p --tools "" --setting-sources "" --model "$SYNTH_MODEL" \
    --system-prompt "You are a synthesiser. You receive three perspectives on a question (facts, benefits, risks). Combine them into one balanced, well-structured answer for the user. Acknowledge tensions where they exist. Do not just concatenate - integrate. Output ONLY the synthesised answer - no preamble, no headers, no meta-commentary about the task." \
    > "$TMP/synth.txt"
ELAPSED=$((SECONDS - START))
printf "${G}  ✓ synthesis returned in ${ELAPSED}s${R}\n"

banner "CONSENSUS ANSWER"
cat "$TMP/synth.txt"
echo
