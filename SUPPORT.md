# Support

Use GitHub Issues for bugs, documentation gaps, installer problems, and feature requests.

Before opening an issue:

```bash
python3 scripts/validate_skill_inventory.py
python3 scripts/reference_freshness.py resources/references --max-age-days 90
```

For dataset-generation behavior, include:

- The command or prompt you used.
- The install target, such as Codex, Claude Code, Cursor, or Copilot.
- Python version and operating system.
- Relevant script output with secrets removed.

For security-sensitive reports, follow `SECURITY.md` instead of opening a public issue.
