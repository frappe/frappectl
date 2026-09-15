# Philosophy

- **For humans and agents, equally.** A TTY gets rich tables and prompts; a pipe (or `--json`) gets clean JSON on stdout and nothing else. Same command, both audiences.
- **A thin, honest wrapper.** Verbs map to the Frappe REST API v2 with little magic, and `api` is always the escape hatch — the CLI never hides the platform underneath.
- **Predictable I/O contract.** stdout is data, stderr is chatter. Exit `0`/`1`/`2`. Errors are plain text with a tip pointing at the fix.
- **Confirmation belongs to the caller.** The CLI never prompts before a mutation, so there is nothing to script around. Humans and agent harnesses decide when to ask. The guardrail that matters lives elsewhere: a read-only profile refuses unsafe verbs.
- **Credentials are the human's job.** Key/secret live in env or the OS keyring — never plaintext, never mutated by the CLI, never set up for you.
- **Self-orienting.** `guide` and `doctype show` let anyone learn the surface before touching a live site. Orient, don't guess.
