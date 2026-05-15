# Release and Packaging

Releases are produced automatically by a tag-triggered GitHub Actions workflow. This page documents what ships inside a release archive, how to cut a new release, and how to install one against a specific tag.

## Runtime Payload

A release archive packages only the runtime payload the installed skill needs:

- `SKILL.md`
- `scripts/`
- `resources/`
- `sub-skills/`

The following paths are excluded from release archives because they are repository-only assets:

- `tests/`
- `docs/`
- `wiki/`
- `workspace/`
- `__pycache__/`
- `*.pyc`
- `*.sqlite`
- governance files: `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`, `SECURITY.md`, `SUPPORT.md`, `CITATION.cff`, `pyproject.toml`

This keeps installed skills small and avoids shipping development-only files.

## Tag-Triggered Release

Pushing a tag matching `v*` triggers `.github/workflows/package-on-tag.yml`, which builds two assets and attaches them to the GitHub Release:

- `ai-dataset-generator-v<version>.zip`
- `ai-dataset-generator-v<version>.tar.gz`

The workflow stages the payload outside the repo, runs `rsync` with the exclusion list above, and produces flat archives (no top-level directory wrapper). The installer auto-detects either layout.

Cut a release by pushing a semver tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Or as a single command:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

The release notes section is generated automatically by `softprops/action-gh-release@v2` from the commits in the tag range.

## Installing From a Release Tag

The bundled `install.sh` accepts an explicit tag via `--ref`:

```bash
bash install.sh --online --ref v0.1.0 --target codex
```

PowerShell on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -Online -Ref v0.1.0 -Target codex
```

Valid `--target` values include `claude`, `codex`, `antigravity`, `cursor`, `windsurf`, `continue`, `copilot`, and `cline`. See [[Installation]] for the full matrix and per-IDE install paths.

## Local Source Mode

When you want to test pre-release changes against an installed skill, point the installer at a working copy instead of a release tag:

```bash
bash install.sh --source local --repo-path . --target claude
```

This copies the same runtime payload (SKILL.md, scripts, resources, sub-skills) from the working tree into the target skill directory, so you can iterate without cutting a tag. Re-run with `--force` to overwrite an existing installation.
