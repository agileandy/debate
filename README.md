# debate

A multi-format AI debate CLI. Pick a format, ask a question, get an iterative multi-persona answer with a Markdown transcript saved to disk.

> **TL;DR** — Four debate formats (Six Thinking Hats, Corporate Boardroom, Socratic, Negotiation), single-file Python script, shells out to the `claude` CLI for every model call. Personas live in YAML and are easy to edit or extend.

---

## What it does

Spins up a roster of role-played personas (e.g. CEO/CTO/CFO for a boardroom, the six de Bono hats for a brainstorm), runs them through a configurable number of rounds where each persona sees the prior transcript, then has a designated synthesiser write the final answer. A convergence judge can stop the loop early when positions stabilise. Optional web search lets personas verify claims and cite sources.

---

## Install

**Requirements**

- macOS or Linux (Windows: use WSL — the script's `uv run` shebang is a UNIX construct)
- The [`claude`](https://github.com/anthropics/claude-code) CLI on your `PATH`, signed in (any auth method)
- [`uv`](https://github.com/astral-sh/uv) for the script's PEP 723 inline dependency resolution

**Clone and wire up**

```bash
# Clone wherever you keep source — anywhere is fine, just don't collide with
# an existing ~/bin/debate directory.
git clone https://github.com/agileandy/debate.git ~/src/debate
chmod +x ~/src/debate/debate.py

# Either alias it…
echo "alias debate='~/src/debate/debate.py'" >> ~/.zshrc
source ~/.zshrc

# …or symlink onto your PATH
ln -s ~/src/debate/debate.py ~/.local/bin/debate
```

First run pulls `pyyaml` via `uv` (a one-off; subsequent runs start from the cache near-instantly).

The script exits with a friendly error if `claude` isn't on `PATH`.

> **Compatibility note** — the script depends on the `claude -p` flags `--system-prompt`, `--tools`, `--setting-sources`, and `--json-schema`. Tested against `claude` from late 2025 onwards. If a future release renames any of these, raise an issue.

---

## Quick start

```bash
debate hats "Should we adopt Rust for our core service?"
debate boardroom --rounds 3 "Should we acquire Acme for $50M?"
debate socratic "Is consciousness substrate-independent?"
debate negotiation --search "Should standups be daily or weekly?"
```

By default, stdout shows per-persona end-of-debate summaries and the final synthesis. The full round-by-round transcript lands in `~/debates/<timestamp>-<type>.md`.

---

## Debate types

| Type | Personas (debaters) | Synthesiser | Default rounds |
|---|---|---|---|
| `hats` | White, Red, Black, Yellow, Green | Blue Hat | 3 |
| `boardroom` | CEO, CTO, CFO, CMO, COO, Legal, Risk & Compliance | Chair | 3 |
| `socratic` | Socrates, Respondent (alternating turns) | Socrates (closing reflection) | 5 |
| `negotiation` | Stakeholder A, Stakeholder B | Mediator (Agreed / Blocked) | 4 |

- **Hats** runs all five debaters in parallel each round; Blue Hat reads the transcript at the end and writes the answer.
- **Boardroom** uses the same parallel pattern. The Chair does not advocate, only synthesises a decision with rationale and follow-ups per seat.
- **Socratic** alternates: round 1 Socrates asks, round 2 Respondent answers, repeat. Convergence is checked from round 4 onward (you need at least two full Q→A pairs before judging).
- **Negotiation** has both stakeholders speak each round seeking alignment. The Mediator outputs two sections — "Agreed" and "Blocked" — with no recommendation.

---

## Options

Every option is shared across all four debate types.

| Option | Default | Notes |
|---|---|---|
| `--rounds N` | per-type default (clamped to 1..10) | Round cap. Loop stops earlier if the convergence judge declares positions stable. |
| `--model MODEL` | `haiku` | Model alias for the debaters. Try `sonnet` or `opus` for richer reasoning at higher cost. |
| `--synth-model MODEL` | `sonnet` | Used for the final synthesis, the convergence judge, and per-persona summaries. |
| `--verbose LEVEL` | `summary` | `full` prints every response in every round. `summary` prints per-persona summaries plus final synthesis. `final` prints only the synthesis. The full transcript is always saved to file unless `--no-save`. |
| `--search` | off | Enables the `WebSearch` tool for every persona call. Slows runs (search calls take 30–90s) and bumps the subprocess timeout from 120s to 300s. Personas are nudged to cite sources inline. |
| `--save PATH` | `~/debates/<ts>-<type>.md` | Where the Markdown transcript is written. |
| `--no-save` | — | Suppress transcript saving. Mutually exclusive with `--save`. |
| `--personas-file PATH` | `<script-dir>/personas.yaml` | Override the personas YAML location. |

> `--verbose summary` (the default) costs one extra `--synth-model` call per debater to produce the summaries. `--verbose final` skips that step.

`debate --help` prints the same table; `debate <type> --help` prints the per-subcommand variant.

---

## How it works

1. Each round, the orchestrator calls `claude -p --model <model> --system-prompt <persona-prompt> --tools "" "<question + prior transcript>"` for every debating persona — in parallel except in Socratic, which alternates.
2. After round ≥2 (≥4 for Socratic, with a hard floor of 2 imposed by the runtime), a convergence judge runs against the latest two rounds with `--json-schema` for reliable structured output. If it returns `{"converged": true}`, the loop exits early. **If the judge errors, the loop continues to the `--rounds` cap and a warning is logged to stderr.**
3. The synthesiser persona reads the full transcript and writes the final answer (Blue Hat, Chair, Socrates' closing reflection, or the Mediator's Agreed/Blocked map).
4. (When `--verbose summary`) one extra synth-model call per persona produces a <100-word summary of that persona's stance.
5. The transcript is rendered to Markdown and saved.

Web search is wired via `--tools "WebSearch"` on every model call when `--search` is on.

---

## Editing personas

Every prompt and every persona lives in `personas.yaml` next to the script. Adding a new role or even a whole new debate type is YAML-only — no Python changes.

**File structure**

```yaml
debate_types:

  <type-name>:
    rounds_default: 3
    min_rounds_before_convergence: 2   # optional, default 2; runtime floor is 2
    pattern: parallel                  # or "alternating" (Socratic-style)
    synthesiser: <role-key>            # must match a role defined below

    roles:
      <role-key>:
        title: "Display Name"
        prompt: |
          You are <X>. Your remit is ...
          (system prompt for this persona)
        debater: true                  # optional, default true; false = synth-only
```

**Tweaking an existing persona** — find its block under `debate_types.<type>.roles.<role>.prompt` and edit the prompt text. The script reloads the YAML on every run; no restart needed.

**Adding a role to an existing type** — add a new `<role-key>` block under `roles`. Provide a `title` and `prompt`. The role joins the debate immediately. (For Socratic's alternating pattern the order matters: roles cycle in YAML declaration order.)

**Adding a whole new debate type** — add a new top-level block under `debate_types`. Pick a `synthesiser` (one of the roles you define), declare at least one debater, and you can call it on the CLI: `debate <your-new-type> "Question?"`. The argparse subparser is generated from the YAML at startup.

**Conventions to follow**

- Keep persona prompts terse. The shipped prompts cap responses at <150 words (hats, boardroom) or <200 words (socratic, negotiation). Going much longer blows the prompt-cache budget across rounds.
- A debater role gets a small runtime suffix appended to its system prompt that nudges multi-round engagement ("respond to specific points others raised — refine, agree, or rebut, don't restate"). When `--search` is on, a second suffix asks for inline citations. You don't need to write either yourself.
- The runtime imposes a floor of 2 on `min_rounds_before_convergence` regardless of YAML — the convergence judge needs at least two completed rounds to compare.

**Validation**

If the YAML is malformed, the synthesiser key doesn't match a role, or a debate type has fewer than the required debaters, `debate.py` exits with a one-line error before any model call. Expect to see something like `boardroom: synthesiser 'chairperson' is not a defined role`.

---

## Output

Every run writes a Markdown transcript to `~/debates/<ISO-timestamp>-<type>.md` unless you pass `--no-save`. The file contains:

- Header (question, started timestamp, models used, search on/off, rounds run, convergence reason if early-stopped)
- Each round, with one section per persona that spoke
- Convergence verdicts where they fired
- Per-persona summaries (when applicable)
- Final synthesis from the type's synthesiser

The transcript is always full fidelity regardless of `--verbose` — verbosity only controls stdout.

---

## Cost notes

The default boardroom run is around **30 model calls**:

- Round 1: 7 debater calls
- Round 2: 7 debater calls + 1 convergence judge call
- Round 3: 7 debater calls (no judge — last round)
- Per-persona summaries: 7 (one per debater, when `--verbose summary`)
- Final synthesis: 1

Tune for cheaper runs:

- `--rounds 1` removes iteration entirely (no convergence judge fires)
- `--verbose final` skips per-persona summaries
- `--model haiku` (default) keeps debaters cheap; the synthesiser stays on Sonnet
- `--no-save` makes no difference to cost — file IO is free

The very cheapest possible run: `debate hats --rounds 1 --verbose final "Q"` — 5 debater calls (Haiku) plus 1 synthesis call (Sonnet) = 6 calls total.

**Rough money** — at the published Haiku/Sonnet rates, expect a default boardroom run on a typical question to cost on the order of **$0.05–$0.30** (more with `--search` and longer transcripts; less if you `--rounds 1`). Treat as ballpark only — your mileage varies with question length, search use, and the model alias you pick.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `error: 'claude' CLI not found on PATH` | `claude` not installed or not on `PATH` | Install from https://github.com/anthropics/claude-code; verify with `claude --version`. |
| `command not found: uv` (when running the script) | `uv` not installed | Install from https://github.com/astral-sh/uv; the script's shebang is `#!/usr/bin/env -S uv run --script`. |
| `personas file not found: ...` | Moved or renamed `personas.yaml` | Either keep it next to `debate.py` or pass `--personas-file PATH`. |
| `claude call timed out after 120s` (or 300s with `--search`) | A model call hung | Re-run; if persistent, try `--model haiku` to reduce per-call latency. |
| Convergence judge `failed (...); continuing` warning on stderr | Judge returned malformed JSON or errored | Benign — loop falls through to the `--rounds` cap and the run still completes. |
| Transcript missing | `--no-save` set, or invalid `--save PATH` | Drop the flag, or pass an absolute path that's writable. |

---

## Repo layout

```
.
├── README.md          (this file)
├── LICENSE            (MIT)
├── CONTRIBUTING.md    (how to propose changes)
├── SECURITY.md        (how to report security issues)
├── .gitignore
├── debate.py          (the harness — single-file Python with PEP 723 deps)
├── personas.yaml      (every persona's system prompt)
└── debate.sh          (DEPRECATED — legacy 3-hat single-shot tool)
```

`debate.sh` is the original bash script the project grew out of. It still works (`debate.sh "Q"` runs the parallel-three-hats-then-synthesise pattern) but is deprecated in favour of `debate.py`. It's kept in-tree so the history is self-contained.

---

## License

MIT. See [LICENSE](LICENSE).
