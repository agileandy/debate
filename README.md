# debate

A multi-format AI debate harness. Pick a format, ask a question, get an iterative multi-persona answer with a transcript on disk.

Four debate types ship out of the box — **Six Thinking Hats**, **Corporate Boardroom**, **Socratic dialogue**, and **Negotiation** — each with its own roster of role-played personas. Personas debate over multiple rounds, see each other's contributions, and stop early when a convergence judge declares positions stable. A designated synthesiser (Blue Hat, Chair, Socrates, or Mediator) writes the final answer.

The whole thing is a single Python script that shells out to the [Claude Code CLI](https://github.com/anthropics/claude-code) for every model call, so authentication and model routing piggy-back on whatever you already have working with `claude`.

---

## Install

**Requirements**

- macOS or Linux
- [`claude`](https://github.com/anthropics/claude-code) on your `PATH` (any auth method)
- [`uv`](https://github.com/astral-sh/uv) (used by the script's shebang to resolve `pyyaml` on first run)

**Clone and wire up**

```bash
git clone https://github.com/agileandy/debate.git ~/bin/debate
chmod +x ~/bin/debate/debate.py

# either add an alias…
echo "alias debate='~/bin/debate/debate.py'" >> ~/.zshrc
source ~/.zshrc

# …or symlink onto your PATH
ln -s ~/bin/debate/debate.py ~/.local/bin/debate
```

First run downloads `pyyaml` via `uv` (about 1ms after the first time, since `uv` caches it).

---

## Quick start

```bash
debate hats "Should we adopt Rust for our core service?"
debate boardroom --rounds 3 "Should we acquire Acme for $50M?"
debate socratic "Is consciousness substrate-independent?"
debate negotiation --search "Should standups be daily or weekly?"
```

Stdout shows per-persona summaries plus the final synthesis (default verbosity). The full transcript lands in `~/debates/<timestamp>-<type>.md`.

---

## Debate types

| Type | Personas (debaters) | Synthesiser | Default rounds |
|---|---|---|---|
| `hats` | White, Red, Black, Yellow, Green | Blue Hat | 3 |
| `boardroom` | CEO, CTO, CFO, CMO, COO, Legal, Risk & Compliance | Chair | 3 |
| `socratic` | Socrates, Respondent (alternating turns) | Socrates (closing reflection) | 5 |
| `negotiation` | Stakeholder A, Stakeholder B | Mediator (Agreed / Blocked) | 4 |

- **Hats** runs all five debaters in parallel each round; Blue Hat reads the transcript at the end and writes the answer.
- **Boardroom** is the same parallel pattern; the Chair does not advocate, only synthesises a decision with rationale and follow-ups per seat.
- **Socratic** alternates: round 1 Socrates asks, round 2 Respondent answers, repeat. Convergence is checked from round 4 onward.
- **Negotiation** has both stakeholders speak each round seeking alignment; the Mediator outputs two sections, "Agreed" and "Blocked", with no recommendation.

---

## Options

Every option is shared across all four debate types.

| Option | Default | Notes |
|---|---|---|
| `--rounds N` | per-type default (1..10) | Round cap. Loop stops earlier if convergence judge declares positions stable. |
| `--model MODEL` | `haiku` | Model alias for the debaters. Try `sonnet` or `opus` for richer reasoning at higher cost. |
| `--synth-model MODEL` | `sonnet` | Model used for synthesis, the convergence judge, and per-persona summaries. |
| `--verbose LEVEL` | `summary` | `full` prints every response in every round. `summary` prints per-persona summaries plus final synthesis. `final` prints only the synthesis. The full transcript is always saved to file unless `--no-save`. |
| `--search` | off | Enables the `WebSearch` tool for every persona call. Slows runs (search calls take 30-90s) and bumps the subprocess timeout from 120s to 300s. Personas are nudged to cite sources. |
| `--save PATH` | `~/debates/<ts>-<type>.md` | Where the Markdown transcript is written. |
| `--no-save` | — | Suppress transcript saving. Mutually exclusive with `--save`. |
| `--personas-file PATH` | `<script-dir>/personas.yaml` | Override the personas YAML location. |

`debate --help` prints the same table; `debate <type> --help` prints the per-subcommand variant.

---

## Editing personas

Every prompt and every persona lives in `personas.yaml` next to the script. Adding a new role or even a new debate type is YAML-only — no Python changes.

**File structure**

```yaml
debate_types:

  <type-name>:
    rounds_default: 3
    min_rounds_before_convergence: 2   # optional, default 2
    pattern: parallel                  # or "alternating" (Socratic-style)
    synthesiser: <role-key>            # must exist in roles below

    roles:
      <role-key>:
        title: "Display Name"
        prompt: |
          You are <X>. Your remit is ...
          (system prompt for this persona)
        debater: true                  # optional, default true; false = synth-only
```

**Tweaking an existing persona** — find its block under `debate_types.<type>.roles.<role>.prompt` and edit the prompt text. The script reloads YAML on every run; no restart needed.

**Adding a role to an existing type** — add a new `<role-key>` block under `roles`. Provide a `title` and `prompt`. The role joins the debate immediately. (For Socratic's alternating pattern the order matters: roles cycle in YAML declaration order.)

**Adding a whole new debate type** — add a new top-level block under `debate_types`. Pick a `synthesiser` (one of the roles you define), declare at least one debater, and you can call it on the CLI: `debate <your-new-type> "Question?"`. The argparse subparser is generated from the YAML.

A debater role gets a small runtime suffix appended to its system prompt that nudges multi-round engagement ("respond to specific points others raised — refine, agree, or rebut, don't restate"). When `--search` is on, a second suffix asks for inline citations. You don't need to write either yourself.

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

The default boardroom config (7 personas × 3 rounds + 2 convergence checks + 7 per-persona summaries + 1 synthesis) is around 31 model calls worst case. Tune for cheaper runs:

- `--rounds 1` removes iteration entirely (no convergence judge)
- `--verbose final` skips per-persona summaries
- `--model haiku` (default) keeps debaters cheap; the synthesiser stays on Sonnet
- `--no-save` makes no difference to cost — file IO is free

The very cheapest possible run: `debate hats --rounds 1 --verbose final "Q"` — 5 haiku calls plus 1 sonnet synthesis.

---

## How it works

1. Each round, the orchestrator calls `claude -p --model <model> --system-prompt <persona-prompt> --tools "" "<question + prior transcript>"` for every debating persona (in parallel, except Socratic which alternates).
2. After round ≥2 (≥4 for Socratic), a convergence judge runs against the latest two rounds with `--json-schema` for reliable structured output. If `{"converged": true}`, the loop exits early.
3. The synthesiser persona reads the full transcript and writes the final answer.
4. (When `--verbose summary`) one extra synth-model call per persona produces a <100-word summary of that persona's stance.
5. The transcript is rendered to Markdown and saved.

Web search is wired via `--tools "WebSearch"` on every model call when `--search` is on.

---

## Repo layout

```
.
├── README.md         (this file)
├── LICENSE           (MIT)
├── .gitignore
├── debate.py         (the harness — single-file Python with PEP 723 deps)
├── personas.yaml     (every persona's system prompt)
└── debate.sh         (legacy 3-hat single-shot tool, kept for reference)
```

`debate.sh` is the original bash script the project grew out of. It's untouched and still works — `debate.sh "Q"` runs the same parallel-three-hats-then-synthesise pattern.

---

## License

MIT. See [LICENSE](LICENSE).
