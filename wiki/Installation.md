# Installation

This page mirrors the README installation detail, but keeps it organized by target and workflow.

Current release tag: `v0.1.0`

Release page:

https://github.com/Bhanunamikaze/ai-dataset-generator/releases/tag/v0.1.0

## IDE Targets

The installer writes the skill runtime (`SKILL.md`, `scripts/`, `sub-skills/`, `resources/`, plus an empty `workspace/`) into each IDE's native skill location.

| Target | Install location | Native format |
|---|---|---|
| `claude` | `~/.claude/skills/dataset-generator` (or `<project>/.claude/skills/dataset-generator` when `.claude` exists locally) | Skill directory |
| `codex` | `~/.codex/skills/dataset-generator` (or `<project>/.codex/skills/dataset-generator` when `.codex` exists locally) | Skill directory |
| `antigravity` | `<project>/.agent/skills/dataset-generator` (or `~/.gemini/antigravity/skills/dataset-generator` when no project root) | Skill directory |
| `global` | Claude + Codex + Antigravity under the user-global homes | User-wide install |
| `all` | Auto-detected per-IDE install for Claude, Codex, and Antigravity | Every supported target |

Other agent IDEs (Claude Cowork, Cursor, Windsurf, Continue, Copilot, Cline) can be enabled by copying the runtime into the IDE's project-local skill directory. See [Manual Install for Other IDEs](#manual-install-for-other-ides) below.

## Quick Install From Release

Use `--online` for normal installs. With no `--target`, online mode installs every supported target.

### Linux and macOS

Install every supported target (auto-detected per-IDE):

```bash
curl -fsSL https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.sh | bash -s -- --online
```

Claude Code only:

```bash
curl -fsSL https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.sh | bash -s -- --online --target claude
```

Codex CLI only:

```bash
curl -fsSL https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.sh | bash -s -- --online --target codex
```

Antigravity only (project-local):

```bash
curl -fsSL https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.sh | bash -s -- --online --target antigravity --project-dir /path/to/your/project
```

User-wide install across Claude, Codex, and Antigravity:

```bash
curl -fsSL https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.sh | bash -s -- --online --target global
```

Auto-detected install across every supported target:

```bash
curl -fsSL https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.sh | bash -s -- --online --target all --project-dir /path/to/your/project
```

Pin a specific release tag:

```bash
curl -fsSLO https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.sh
bash install.sh --online --ref v0.1.0 --target codex --force
```

### Windows PowerShell

Download the installer:

```powershell
iwr https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.ps1 -OutFile install.ps1
```

Install every supported target:

```powershell
pwsh ./install.ps1 --online
```

Claude Code only:

```powershell
pwsh ./install.ps1 --online --target claude
```

Codex CLI only:

```powershell
pwsh ./install.ps1 --online --target codex
```

User-wide install across Claude, Codex, and Antigravity:

```powershell
pwsh ./install.ps1 --online --target global
```

Auto-detected install across every supported target for a project:

```powershell
pwsh ./install.ps1 --online --target all --project-dir C:\path\to\your\project
```

Pin a release tag:

```powershell
pwsh ./install.ps1 --online --ref v0.1.0 --target codex --force
```

## Install From Source

Use source installs when developing the skill or testing unreleased changes. Pass `--source local` (or use `--repo-path`) to force the installer to copy from a local checkout.

```bash
git clone https://github.com/Bhanunamikaze/ai-dataset-generator.git
cd ai-dataset-generator
```

Claude Code:

```bash
bash install.sh --source local --target claude
```

Codex CLI:

```bash
bash install.sh --source local --target codex
```

Antigravity (project-local):

```bash
bash install.sh --source local --target antigravity --project-dir /path/to/your/project
```

User-wide global install:

```bash
bash install.sh --source local --target global
```

Auto-detected install across every target:

```bash
bash install.sh --source local --target all --project-dir /path/to/your/project
```

Install from a specific checkout path:

```bash
bash install.sh --target codex --repo-path /path/to/another/clone
```

## Manual Install for Other IDEs

The native installer manages Claude, Codex, and Antigravity. For other agent IDEs, install the runtime into the IDE's project-local skill directory by copying the four runtime paths:

```bash
git clone https://github.com/Bhanunamikaze/ai-dataset-generator.git
cd ai-dataset-generator

# Pick the destination based on your IDE
DEST=<one of the rows in the table below>
mkdir -p "$DEST"
rsync -a --exclude '__pycache__/' --exclude '*.pyc' \
    SKILL.md scripts sub-skills resources "$DEST"/
```

| IDE | Suggested destination |
|---|---|
| Claude Cowork | `<project>/.claude/skills/dataset-generator` |
| Cursor | `<project>/.cursor/skills/dataset-generator` (and reference `SKILL.md` from a Cursor MDC rule) |
| Windsurf | `<project>/.windsurf/skills/dataset-generator` |
| Continue | `<project>/.continue/skills/dataset-generator` |
| Copilot | `<project>/.github/skills/dataset-generator` (and reference `SKILL.md` from `.github/copilot-instructions.md`) |
| Cline | `<project>/.cline/skills/dataset-generator` (and add a `SKILL.md` reference inside `.clinerules`) |

These IDEs do not have a built-in skill resolver yet, so reference `SKILL.md` from the IDE's rule or instructions file to make the agent aware of the `dataset` command surface.

## Safer Remote Install

If you want to inspect the installer before running it:

```bash
curl -fsSLO https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.sh
less install.sh
bash install.sh --online --target codex
```

PowerShell equivalent:

```powershell
iwr https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.ps1 -OutFile install.ps1
notepad install.ps1
pwsh ./install.ps1 --online --target codex
```

## Installer Flags

| Flag | Default | Purpose |
|---|---|---|
| `--target <name>` | `antigravity` | Pick one target (`antigravity`, `claude`, `codex`, `global`, `all`). With `--online` and no target, defaults to `all`. |
| `--project-dir <path>` | current directory | Destination project for project-local targets. Also flips Claude/Codex to project-local mode when a `.claude` or `.codex` directory exists. |
| `--skill-name <name>` | `dataset-generator` | Override the installed skill folder name. |
| `--online` | off | Fetch the release/branch archive payload from GitHub instead of using the local tree. Implies `--force` for extracted payloads. |
| `--ref <branch-or-tag>` | `main` | Branch or tag to use in online mode. Use release tags for stable installs. |
| `--repo-url <url>` | upstream repo | Override the remote source repository. |
| `--source <auto|local|remote>` | `auto` | Force source resolution mode. `local` uses the script directory; `remote` clones the repo. |
| `--repo-path <path>` | empty | Use a specific local checkout as the install source. |
| `--install-deps` | off | Install Python dependencies (`pip install --user -r requirements.txt`). |
| `--force` | off | Overwrite an existing installed skill. Online mode implies force. |
| `-h`, `--help` | off | Show installer usage. |

## Optional Dependencies

Core scripts run on Python 3.9+ with a small set of optional dependencies.

From a source checkout:

```bash
python3 -m pip install -r requirements.txt
```

Minimal manual install (covers schema validation only):

```bash
python3 -m pip install jsonschema
```

Web research extras (HTTP, HTML extraction, search backends):

```bash
python3 -m pip install requests beautifulsoup4 trafilatura duckduckgo-search
```

JavaScript-enabled URL collection requires Playwright:

```bash
python3 -m pip install -r requirements-browser.txt
python3 -m playwright install chromium
```

Optional GPT Researcher backend:

```bash
python3 -m pip install -r requirements-research.txt
```

The installer can also auto-install the core requirements when invoked with `--install-deps`:

```bash
bash install.sh --target codex --install-deps
```

## Verify Installation

After installing, restart your IDE session and try one of these prompts:

```text
Generate a 500-example customer support dataset.
```

```text
Use web research to build a fintech FAQ dataset.
```

```text
Normalize this CSV into OpenAI JSONL.
```

```text
Verify and score this dataset.jsonl.
```

For Codex you can confirm the install on disk:

```bash
ls ~/.codex/skills/dataset-generator/SKILL.md
```

For Claude:

```bash
ls ~/.claude/skills/dataset-generator/SKILL.md
```

For Antigravity (project-local):

```bash
ls /path/to/your/project/.agent/skills/dataset-generator/SKILL.md
```

If `SKILL.md` is present in the expected location, the runtime is in place.

## What Gets Installed

Installed skill bundles include only:

- `SKILL.md`
- `scripts/`
- `sub-skills/`
- `resources/`

The installer also creates an empty `workspace/` directory for pipeline state.

Repository-only files are not required inside the skill runtime:

- `tests/`
- `docs/`
- `workspace/<sqlite>`
- `.github/`
- `wiki/`
- governance docs (`README.md`, `CONTRIBUTING.md`, `SECURITY.md`)
- generated audit reports

Release packaging uses this runtime allowlist so installed skills stay small and predictable. See [[Release and Packaging]] for the tag-publish workflow.

## Common Issues

### Existing Skill Directory

If the target already exists, rerun with:

```bash
bash install.sh --target codex --force
```

### Online Mode With a Pinned Tag

```bash
bash install.sh --online --ref v0.1.0 --target codex --force
```

This downloads the release tag archive instead of the latest tag.

### Python Dependency Install Fails

The installer falls back to installing just `jsonschema` if the full requirements install fails. To finish manually:

```bash
python3 -m pip install --user -r ~/.codex/skills/dataset-generator/../../<path>/requirements.txt
```

Or just install the requirements file from your source checkout.

### Windows Execution Policy

If PowerShell blocks local scripts, run PowerShell as a user with script execution allowed, or use:

```powershell
pwsh -ExecutionPolicy Bypass -File ./install.ps1 --online --target codex
```
