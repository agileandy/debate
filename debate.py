#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml>=6.0",
# ]
# ///
"""
debate.py — multi-format AI debate harness.

Successor to debate.sh. Supports four debate types (hats, boardroom,
socratic, negotiation), iterative rounds where each persona sees prior turns,
convergence-capped loops, configurable verbosity, optional web search via the
claude CLI's WebSearch tool, and a single --model flag.

Personas live in ~/bin/personas.yaml (or --personas-file). The script shells
out to the `claude` CLI for every model call — auth and model selection are
handled by the CLI.

Usage:
    debate.py hats "Should we adopt Rust for our core service?"
    debate.py boardroom --rounds 3 "Should we acquire Acme for $50M?"
    debate.py socratic "Is consciousness substrate-independent?"
    debate.py negotiation --search "API rate limit: 100/sec or 50/sec?"
    echo "..." | debate.py hats
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

# --- ANSI ---------------------------------------------------------------------
B = "\033[1m"
C = "\033[36m"
G = "\033[32m"
Y = "\033[33m"
RD = "\033[31m"
D = "\033[2m"
R = "\033[0m"


def banner(label: str) -> None:
    print(f"\n{C}{B}═══ {label} ═══{R}\n")


def info(msg: str) -> None:
    print(f"{D}  {msg}{R}")


def warn(msg: str) -> None:
    print(f"{Y}  ! {msg}{R}", file=sys.stderr)


# --- Config -------------------------------------------------------------------
DEFAULT_PERSONAS = Path(__file__).resolve().parent / "personas.yaml"
DEFAULT_DEBATE_DIR = Path.home() / "debates"
DEFAULT_TIMEOUT = 120
SEARCH_TIMEOUT = 300

DEBATE_ADDENDUM = (
    "\n\nYou are participating in a multi-round debate. In rounds beyond the "
    "first, engage with specific points raised by other participants — refine, "
    "agree, or rebut, don't restate."
)
SEARCH_ADDENDUM = (
    "\n\nYou may use the WebSearch tool to verify claims. Cite sources inline "
    "as [domain.tld]."
)

CONVERGENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "converged": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["converged", "reason"],
}


@dataclass
class Role:
    key: str
    title: str
    prompt: str
    debater: bool = True


@dataclass
class DebateType:
    name: str
    rounds_default: int
    synthesiser: str
    roles: dict[str, Role]
    pattern: str = "parallel"
    min_rounds_before_convergence: int = 2

    @property
    def debaters(self) -> list[Role]:
        return [r for r in self.roles.values() if r.debater]


@dataclass
class Turn:
    role_key: str
    role_title: str
    round_no: int
    text: str


@dataclass
class DebateResult:
    debate_type: str
    question: str
    started: str
    model: str
    synth_model: str
    search: bool
    rounds_run: int
    rounds_cap: int
    converged: bool
    convergence_reason: str
    turns: list[Turn]
    persona_summaries: dict[str, str] = field(default_factory=dict)
    synthesis: str = ""


# --- Personas loader ----------------------------------------------------------
def load_personas(path: Path) -> dict[str, DebateType]:
    if not path.exists():
        sys.exit(f"personas file not found: {path}")
    raw = yaml.safe_load(path.read_text())
    types: dict[str, DebateType] = {}
    for tname, tcfg in (raw.get("debate_types") or {}).items():
        roles = {}
        for rkey, rcfg in (tcfg.get("roles") or {}).items():
            roles[rkey] = Role(
                key=rkey,
                title=rcfg["title"],
                prompt=rcfg["prompt"].rstrip(),
                debater=rcfg.get("debater", True),
            )
        synth = tcfg["synthesiser"]
        if synth not in roles:
            sys.exit(f"{tname}: synthesiser '{synth}' is not a defined role")
        debaters = [r for r in roles.values() if r.debater]
        if len(debaters) < 1:
            sys.exit(f"{tname}: need at least 1 debater role")
        types[tname] = DebateType(
            name=tname,
            rounds_default=int(tcfg.get("rounds_default", 3)),
            synthesiser=synth,
            roles=roles,
            pattern=tcfg.get("pattern", "parallel"),
            min_rounds_before_convergence=int(
                tcfg.get("min_rounds_before_convergence", 2)
            ),
        )
    if not types:
        sys.exit("no debate_types found in personas file")
    return types


# --- claude CLI wrapper -------------------------------------------------------
def call_claude(
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    search: bool = False,
    json_schema: dict | None = None,
    timeout: int | None = None,
) -> str:
    """Invoke `claude -p` and return stdout. Raises RuntimeError on failure."""
    if timeout is None:
        timeout = SEARCH_TIMEOUT if search else DEFAULT_TIMEOUT

    cmd = [
        "claude",
        "-p",
        "--setting-sources",
        "",
        "--model",
        model,
        "--system-prompt",
        system_prompt,
    ]
    if search:
        cmd += ["--tools", "WebSearch"]
    else:
        cmd += ["--tools", ""]
    if json_schema is not None:
        cmd += ["--json-schema", json.dumps(json_schema)]
    cmd.append(user_prompt)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude call timed out after {timeout}s") from None

    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip() or "no output"
        raise RuntimeError(f"claude exited {proc.returncode}: {err}")
    return proc.stdout.strip()


# --- Prompt builders ----------------------------------------------------------
def build_system(role: Role, *, search: bool, in_debate: bool) -> str:
    parts = [role.prompt]
    if in_debate and role.debater:
        parts.append(DEBATE_ADDENDUM)
    if search:
        parts.append(SEARCH_ADDENDUM)
    return "".join(parts)


def render_transcript(turns: list[Turn]) -> str:
    if not turns:
        return "(no prior turns)"
    by_round: dict[int, list[Turn]] = {}
    for t in turns:
        by_round.setdefault(t.round_no, []).append(t)
    out = []
    for r in sorted(by_round):
        out.append(f"=== Round {r} ===")
        for t in by_round[r]:
            out.append(f"--- {t.role_title} ---")
            out.append(t.text)
        out.append("")
    return "\n".join(out)


def build_user_prompt(question: str, turns: list[Turn], round_no: int) -> str:
    if round_no == 1 or not turns:
        return question
    return (
        f"Original question:\n{question}\n\n"
        f"Debate so far:\n{render_transcript(turns)}\n\n"
        f"It is round {round_no}. Provide your updated position. Engage with "
        f"specific points raised by others — refine, agree, or rebut, don't "
        f"restate. Be concise."
    )


# --- Round execution ----------------------------------------------------------
def speakers_for_round(dt: DebateType, round_no: int) -> list[Role]:
    debaters = dt.debaters
    if dt.pattern == "alternating":
        return [debaters[(round_no - 1) % len(debaters)]]
    return debaters


def run_round(
    dt: DebateType,
    question: str,
    prior_turns: list[Turn],
    round_no: int,
    *,
    model: str,
    search: bool,
) -> list[Turn]:
    speakers = speakers_for_round(dt, round_no)
    user_prompt = build_user_prompt(question, prior_turns, round_no)
    new_turns: list[Turn] = []

    def task(role: Role) -> Turn:
        sys_prompt = build_system(role, search=search, in_debate=True)
        text = call_claude(model, sys_prompt, user_prompt, search=search)
        return Turn(role.key, role.title, round_no, text)

    if len(speakers) == 1:
        new_turns.append(task(speakers[0]))
    else:
        with cf.ThreadPoolExecutor(max_workers=len(speakers)) as ex:
            futures = {ex.submit(task, role): role for role in speakers}
            done = {}
            for fut in cf.as_completed(futures):
                role = futures[fut]
                done[role.key] = fut.result()
            for role in speakers:
                new_turns.append(done[role.key])
    return new_turns


# --- Convergence judge --------------------------------------------------------
def convergence_judge(
    turns: list[Turn],
    *,
    synth_model: str,
) -> tuple[bool, str]:
    if not turns:
        return False, "no turns"
    last_round = max(t.round_no for t in turns)
    last_two = [t for t in turns if t.round_no >= last_round - 1]
    transcript = render_transcript(last_two)
    sys_prompt = (
        "You judge whether a multi-agent debate has converged. Read the last "
        "two rounds. Converged = positions stable, no substantively new "
        "arguments, agreement levels not changing. Respond with JSON only."
    )
    user_prompt = (
        f"Last two rounds of the debate:\n\n{transcript}\n\n"
        "Has the debate converged?"
    )
    try:
        out = call_claude(
            synth_model,
            sys_prompt,
            user_prompt,
            search=False,
            json_schema=CONVERGENCE_SCHEMA,
        )
        data = _extract_json(out)
        return bool(data.get("converged", False)), str(data.get("reason", ""))
    except Exception as exc:  # noqa: BLE001
        warn(f"convergence judge failed ({exc}); continuing")
        return False, f"judge error: {exc}"


def _extract_json(s: str) -> dict:
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"could not parse JSON from: {s[:200]}")


# --- Synthesis & summaries ----------------------------------------------------
def synthesise(
    dt: DebateType,
    question: str,
    turns: list[Turn],
    *,
    synth_model: str,
    search: bool,
) -> str:
    role = dt.roles[dt.synthesiser]
    sys_prompt = build_system(role, search=search, in_debate=False)
    user_prompt = (
        f"Question:\n{question}\n\nFull debate transcript:\n"
        f"{render_transcript(turns)}\n\nProduce your output."
    )
    return call_claude(synth_model, sys_prompt, user_prompt, search=search)


def per_persona_summary(
    role: Role,
    role_turns: list[Turn],
    *,
    synth_model: str,
) -> str:
    sys_prompt = (
        "Summarise this debater's final stance in <100 words. Capture only "
        "their position and key reasoning. No meta-commentary, no headers."
    )
    body = "\n\n".join(f"Round {t.round_no}: {t.text}" for t in role_turns)
    user_prompt = f"Debater: {role.title}\n\nTheir contributions:\n{body}"
    return call_claude(synth_model, sys_prompt, user_prompt, search=False)


# --- Driver -------------------------------------------------------------------
def run_debate(
    dt: DebateType,
    question: str,
    *,
    rounds_cap: int,
    model: str,
    synth_model: str,
    search: bool,
    verbose: str,
) -> DebateResult:
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    turns: list[Turn] = []
    converged = False
    reason = ""
    rounds_run = 0

    banner("QUESTION")
    print(question)
    info(
        f"type={dt.name}  model={model}  synth-model={synth_model}  "
        f"search={'on' if search else 'off'}  rounds-cap={rounds_cap}  "
        f"verbose={verbose}"
    )

    for r in range(1, rounds_cap + 1):
        info(
            f"round {r}/{rounds_cap} — speaking: "
            + ", ".join(s.title for s in speakers_for_round(dt, r))
        )
        new_turns = run_round(
            dt, question, turns, r, model=model, search=search
        )
        turns.extend(new_turns)
        rounds_run = r

        if verbose == "full":
            for t in new_turns:
                banner(f"{t.role_title} — round {r}")
                print(t.text)

        if r >= max(dt.min_rounds_before_convergence, 2) and r < rounds_cap:
            info("checking convergence…")
            converged, reason = convergence_judge(turns, synth_model=synth_model)
            if verbose == "full":
                banner(f"Convergence verdict (after round {r})")
                print(f"converged={converged}  reason={reason}")
            if converged:
                info(f"converged at round {r}: {reason}")
                break

    persona_summaries: dict[str, str] = {}
    if verbose == "summary":
        info("generating per-persona summaries…")
        for role in dt.debaters:
            role_turns = [t for t in turns if t.role_key == role.key]
            if not role_turns:
                continue
            persona_summaries[role.key] = per_persona_summary(
                role, role_turns, synth_model=synth_model
            )

    info(f"synthesising via {dt.roles[dt.synthesiser].title} ({synth_model})…")
    synth_text = synthesise(
        dt, question, turns, synth_model=synth_model, search=search
    )

    if verbose == "summary":
        for role in dt.debaters:
            if role.key in persona_summaries:
                banner(f"{role.title} — summary")
                print(persona_summaries[role.key])
        banner(f"SYNTHESIS — {dt.roles[dt.synthesiser].title}")
        print(synth_text)
    elif verbose == "final":
        banner("SYNTHESIS")
        print(synth_text)
    else:
        banner(f"SYNTHESIS — {dt.roles[dt.synthesiser].title}")
        print(synth_text)

    return DebateResult(
        debate_type=dt.name,
        question=question,
        started=started,
        model=model,
        synth_model=synth_model,
        search=search,
        rounds_run=rounds_run,
        rounds_cap=rounds_cap,
        converged=converged,
        convergence_reason=reason,
        turns=turns,
        persona_summaries=persona_summaries,
        synthesis=synth_text,
    )


# --- Markdown writer ----------------------------------------------------------
def render_markdown(result: DebateResult, dt: DebateType) -> str:
    lines: list[str] = []
    lines.append(f"# Debate: {result.debate_type}")
    lines.append("")
    lines.append(f"**Question:** {result.question}")
    lines.append(f"**Started:** {result.started}")
    converged_note = (
        f"converged after round {result.rounds_run}"
        if result.converged
        else f"ran {result.rounds_run}/{result.rounds_cap} rounds"
    )
    lines.append(
        f"**Model:** {result.model}  |  **Synth model:** {result.synth_model}  "
        f"|  **Search:** {'on' if result.search else 'off'}  |  "
        f"**Rounds:** {converged_note}"
    )
    if result.convergence_reason:
        lines.append(f"**Convergence reason:** {result.convergence_reason}")
    lines.append("")

    by_round: dict[int, list[Turn]] = {}
    for t in result.turns:
        by_round.setdefault(t.round_no, []).append(t)
    for r in sorted(by_round):
        lines.append(f"## Round {r}")
        lines.append("")
        for t in by_round[r]:
            lines.append(f"### {t.role_title}")
            lines.append("")
            lines.append(t.text)
            lines.append("")

    if result.persona_summaries:
        lines.append("## Per-persona summaries")
        lines.append("")
        for role in dt.debaters:
            if role.key in result.persona_summaries:
                lines.append(f"### {role.title}")
                lines.append("")
                lines.append(result.persona_summaries[role.key])
                lines.append("")

    lines.append(f"## Synthesis ({dt.roles[dt.synthesiser].title})")
    lines.append("")
    lines.append(result.synthesis)
    lines.append("")
    return "\n".join(lines)


def default_save_path(debate_type: str) -> Path:
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    return DEFAULT_DEBATE_DIR / f"{ts}-{debate_type}.md"


# --- CLI ----------------------------------------------------------------------
def read_question(args: argparse.Namespace) -> str:
    parts = args.question or []
    if parts:
        return " ".join(parts).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def build_parser(types: dict[str, DebateType]) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--rounds", type=int, default=None,
                        help="Round cap (default: per-type default; max 10)")
    common.add_argument("--model", default="haiku",
                        help="Model alias for debaters (default: haiku)")
    common.add_argument("--synth-model", default="sonnet",
                        help="Model for synthesis/judge/summary (default: sonnet)")
    common.add_argument("--verbose", choices=["full", "summary", "final"],
                        default="summary",
                        help="Output verbosity (default: summary)")
    common.add_argument("--search", action="store_true",
                        help="Allow personas to use the WebSearch tool")
    save_group = common.add_mutually_exclusive_group()
    save_group.add_argument("--save", type=Path, default=None,
                            help="Path to write Markdown transcript")
    save_group.add_argument("--no-save", action="store_true",
                            help="Do not write a transcript file")
    common.add_argument("--personas-file", type=Path, default=DEFAULT_PERSONAS,
                        help=f"Personas YAML (default: {DEFAULT_PERSONAS})")
    common.add_argument("question", nargs="*",
                        help="The question (or pipe via stdin)")

    parser = argparse.ArgumentParser(
        prog="debate",
        description=(
            "Multi-format AI debate harness. Pick a debate type, ask a "
            "question, get an iterative multi-persona answer."
        ),
        epilog=(
            "Common options (apply to every debate type — also visible via\n"
            "`debate <type> --help`):\n"
            "  --rounds N              Round cap. Default per type (hats=3,\n"
            "                          boardroom=3, socratic=5, negotiation=4),\n"
            "                          clamped 1..10. Loop stops earlier if the\n"
            "                          convergence judge declares positions stable.\n"
            "  --model MODEL           Model alias used by every debater.\n"
            "                          Default: haiku. Try sonnet or opus for\n"
            "                          richer reasoning at higher cost.\n"
            "  --synth-model MODEL     Model used for synthesis, the convergence\n"
            "                          judge, and per-persona summaries.\n"
            "                          Default: sonnet.\n"
            "  --verbose LEVEL         full     — print every persona's response\n"
            "                                     in every round, plus synthesis.\n"
            "                          summary  — print per-persona end-of-debate\n"
            "                                     summary + synthesis (DEFAULT).\n"
            "                          final    — print only the final synthesis.\n"
            "                          (Full transcript is always saved to file\n"
            "                          unless --no-save.)\n"
            "  --search                Allow personas to use the WebSearch tool.\n"
            "                          Off by default. Slows runs (search calls\n"
            "                          take 30-90s); subprocess timeout bumps to\n"
            "                          300s. Personas are nudged to cite sources.\n"
            "  --save PATH             Write the Markdown transcript to PATH.\n"
            "                          Default: ~/debates/<ISO-timestamp>-<type>.md\n"
            "  --no-save               Do not write a transcript file.\n"
            "                          Mutually exclusive with --save.\n"
            "  --personas-file PATH    Override the personas YAML location.\n"
            "                          Default: <script-dir>/personas.yaml\n"
            "\n"
            "Examples:\n"
            "  debate hats \"Should we adopt Rust?\"\n"
            "  debate hats --rounds 5 --verbose full \"...\"\n"
            "  debate boardroom --model opus --rounds 3 \"Acquire Acme for $50M?\"\n"
            "  debate socratic \"Is consciousness substrate-independent?\"\n"
            "  debate negotiation --search \"Standups daily or weekly?\"\n"
            "  debate hats --no-save --verbose final \"What is 2+2?\"\n"
            "  echo \"Should we adopt Rust?\" | debate hats\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(
        dest="debate_type",
        required=True,
        title="debate types",
        metavar="<type>",
    )
    descriptions = {
        "hats": "Six de Bono Thinking Hats; Blue Hat synthesises.",
        "boardroom": "CEO/CTO/CFO/CMO/COO/Legal/Risk; Chair synthesises.",
        "socratic": "Socrates ↔ Respondent, alternating Q→A.",
        "negotiation": "Two stakeholders seek alignment; Mediator emits Agreed/Blocked.",
    }
    for tname, dt in types.items():
        sub.add_parser(
            tname,
            parents=[common],
            help=descriptions.get(tname, f"{tname} debate"),
            description=descriptions.get(tname, f"{tname} debate"),
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--personas-file", type=Path, default=DEFAULT_PERSONAS)
    pre_args, _ = pre.parse_known_args(argv)
    types = load_personas(pre_args.personas_file)

    parser = build_parser(types)
    args = parser.parse_args(argv)
    dt = types[args.debate_type]

    question = read_question(args)
    if not question:
        parser.error("question is required (positional args or stdin)")

    rounds_cap = args.rounds if args.rounds is not None else dt.rounds_default
    rounds_cap = max(1, min(10, rounds_cap))

    try:
        result = run_debate(
            dt,
            question,
            rounds_cap=rounds_cap,
            model=args.model,
            synth_model=args.synth_model,
            search=args.search,
            verbose=args.verbose,
        )
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except RuntimeError as exc:
        print(f"\n{RD}error:{R} {exc}", file=sys.stderr)
        return 1

    if not args.no_save:
        save_path = args.save or default_save_path(dt.name)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(render_markdown(result, dt))
        info(f"transcript saved → {save_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
