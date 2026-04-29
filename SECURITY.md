# Security

This is a hobby-scale CLI tool with no network surface of its own — it shells out to the [`claude`](https://github.com/anthropics/claude-code) CLI for every model call, and the only inputs it processes are the question you pass in, the YAML personas file you control, and the responses Claude returns.

If you find a security issue (e.g. a way for a crafted personas file or transcript to escape into the host shell), please:

1. **Do not** open a public issue.
2. Open a private security advisory via GitHub: <https://github.com/agileandy/debate/security/advisories/new>.

For broader concerns about the underlying `claude` CLI or Anthropic API, report them to Anthropic directly via the channels documented in the `claude` repo.
