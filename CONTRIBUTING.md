# Contributing

Thanks for considering a contribution. This is a small, hobby-scale project — keep PRs focused.

## How

1. Open an issue first for anything beyond a typo or a one-line fix, so we can agree on scope.
2. Fork, branch (`feat/<short-name>`, `fix/<short-name>`, `docs/<short-name>`), make the change.
3. Run `./debate.py --help` and at least one debate type end-to-end before opening the PR.
4. Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages (`feat: …`, `fix: …`, `docs: …`, `chore: …`).
5. PR title in the same style; PR description should explain the change in 2–4 sentences.

## What's in scope

- New debate types or personas (YAML-only is preferred — no Python changes if possible)
- Bug fixes
- Documentation improvements
- New CLI flags that genuinely earn their keep

## What's out of scope (for now)

- Switching the runtime from the `claude` CLI to the Anthropic SDK directly
- Adding a web UI or daemon mode
- Wiring in non-Anthropic model providers

If you have strong feelings about any of those, open an issue first to discuss.

## Tests

There is no test suite yet. Manual smoke tests across all four debate types with `--rounds 1 --verbose final` is the current bar. If you add complexity that justifies tests, please add them.
