#!/usr/bin/env pwsh

$ErrorActionPreference = 'Stop'

$REPO_URL        = if ($env:REPO_URL) { $env:REPO_URL } else { 'https://github.com/Bhanunamikaze/ai-dataset-generator.git' }
$GITHUB_REPO     = if ($env:GITHUB_REPO) { $env:GITHUB_REPO } else { 'Bhanunamikaze/ai-dataset-generator' }
$GITHUB_REF      = if ($env:GITHUB_REF)  { $env:GITHUB_REF }  else { 'main' }
$SKILL_NAME      = 'dataset-generator'
$TARGET          = 'claude'
$TARGET_EXPLICIT = $false
$PROJECT_DIR     = (Get-Location).Path
$PROJECT_DIR_EXPLICIT = $false
$FORCE           = $false
$INSTALL_DEPS    = $false
$INSTALL_PLAYWRIGHT = $false
$ONLINE_MODE     = $false
$SOURCE_MODE     = 'auto'
$REPO_PATH       = ''
$TEMP_DIR        = $null

# docs/ and tests/ are intentionally excluded — docs/ only holds README
# screenshots, and tests/ is for repository CI rather than installed skills.
$REQUIRED_PATHS  = @('SKILL.md', 'scripts', 'resources', 'sub-skills')

# Shared invocation block written into every IDE-native format file.
$SKILL_INVOCATION_TEXT = @'
# AI Dataset Generator Skill

You have access to the AI Dataset Generator skill — a tool-native dataset
pipeline for Claude Code, Codex, Antigravity, Cursor, Windsurf, Continue,
Copilot, and Cline. It splits work between reasoning (LLM) and deterministic
processing (local Python + SQLite-backed resumable state).

## Activate this skill when the user wants to

- Generate a training dataset (SFT or DPO) from a topic, URLs, or reference material
- Build a research-grounded dataset using web search or local files
- Normalize, verify, deduplicate, or audit an existing JSONL / CSV dataset
- Export a dataset to OpenAI, HuggingFace, CSV, or custom flat formats
- Run a corpus-level audit for context leakage, coverage gaps, synthetic
  fingerprints, and train/test split disjointness

## Command surface

| Command | Purpose |
|---|---|
| `dataset generate "<request>" [--count N]` | Topic / URL / reference / research-driven generation; defaults to 500 records |
| `dataset collect "<topic|urls|paths>"` | Raw web/URL/local content collection — outputs draft material |
| `dataset verify <file>` | DB-backed audit + cleanup of an existing dataset |
| `dataset audit [file]` | Severity-classified corpus-quality report |
| `dataset export --format <openai|huggingface|csv|jsonl|all>` | Final export + auto-generated DATA_CARD.md |

When the user describes a dataset task in natural language, follow
`SKILL.md` from the installed skill directory.
'@

function Show-Usage {
@'
AI Dataset Generator Skill Installer (Windows / PowerShell)

Each IDE target installs the skill in that IDE's native format:
  claude / codex / antigravity  ->  skills\ directory  (native skill support)
  cowork                        ->  .claude\skills\    (project-scoped; commit to git)
  cursor                        ->  .cursor\rules\dataset-generator.mdc   (MDC rule)
  windsurf                      ->  .windsurf\rules\dataset-generator.md  (Windsurf rule)
  copilot                       ->  .github\copilot-instructions.md
  cline                         ->  .clinerules
  continue                      ->  .continue\prompts\dataset-generator.prompt

Usage:
  pwsh ./install.ps1 [options]

Options:
  --target <target>
      Install target (default: claude). Valid targets:
        claude       ->  ~\.claude\skills\dataset-generator
        codex        ->  ~\.codex\skills\dataset-generator
        antigravity  ->  <project>\.agent\skills\dataset-generator
        cowork       ->  <project>\.claude\skills\dataset-generator  (project-scoped, commit to git)
        cursor       ->  <project>\.cursor\rules\dataset-generator.mdc
        windsurf     ->  <project>\.windsurf\rules\dataset-generator.md
        continue     ->  <project>\.continue\prompts\dataset-generator.prompt
        copilot      ->  <project>\.github\copilot-instructions.md
        cline        ->  <project>\.clinerules
        global       ->  claude + codex (user-wide)
        project      ->  antigravity + cowork + cursor + windsurf + continue + copilot + cline
        all          ->  global + project (every target)

  --project-dir <path>         Project directory for project-local installs (default: cwd)
  --skill-name <name>          Installed folder name for skills-dir targets (default: dataset-generator)
  --repo-url <url>             Git URL for remote source installs
  --source <auto|local|remote> Source mode (default: auto)
  --repo-path <path>           Use a specific local checkout as the install source
  --online                     Fetch latest release zip from GitHub instead of cloning.
                               When no --target is supplied, defaults to --target all.
  --ref <branch-or-tag>        Branch / tag to fetch in --online mode (default: main)
  --install-deps               Install Python dependencies from requirements.txt
  --install-playwright         Also install Playwright + Chromium
  --force                      Overwrite an existing installed skill
  -h, --help                   Show this help

Examples:
  pwsh ./install.ps1 --target claude
  pwsh ./install.ps1 --target global
  pwsh ./install.ps1 --target project --project-dir C:\path\to\your\project
  pwsh ./install.ps1 --target cursor  --project-dir C:\path\to\your\project
  pwsh ./install.ps1 --target all     --project-dir C:\path\to\your\project
  pwsh ./install.ps1 --online
  pwsh ./install.ps1 --online --ref develop
'@ | Write-Host
}

function Require-Cmd {
    param([Parameter(Mandatory = $true)][string]$Cmd)
    if (-not (Get-Command -Name $Cmd -ErrorAction SilentlyContinue)) {
        throw "Error: required command not found: $Cmd"
    }
}

# Resolve a usable Python interpreter. Windows installs usually have `python` or
# the `py` launcher, not `python3`. Returns @{ Command = '...'; PrefixArgs = @() }
# so callers can do: & $py.Command @($py.PrefixArgs + @('-m','pip', ...))
$script:PYTHON_CACHE = $null
function Resolve-Python {
    if ($script:PYTHON_CACHE) { return $script:PYTHON_CACHE }
    foreach ($name in @('python3','python')) {
        if (Get-Command -Name $name -ErrorAction SilentlyContinue) {
            $script:PYTHON_CACHE = @{ Command = $name; PrefixArgs = @() }
            return $script:PYTHON_CACHE
        }
    }
    if (Get-Command -Name 'py' -ErrorAction SilentlyContinue) {
        $script:PYTHON_CACHE = @{ Command = 'py'; PrefixArgs = @('-3') }
        return $script:PYTHON_CACHE
    }
    throw "Error: no Python interpreter found. Install Python 3.8+ (tried: python3, python, py)"
}

function Resolve-Dir {
    param([Parameter(Mandatory = $true)][string]$Dir)
    if (-not (Test-Path -LiteralPath $Dir -PathType Container)) {
        throw "Error: directory not found: $Dir"
    }
    return (Resolve-Path -LiteralPath $Dir).Path
}

function Get-RelativePathCompat {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $baseFull = [System.IO.Path]::GetFullPath($BasePath)
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    $relativeMethod = [System.IO.Path].GetMethod(
        'GetRelativePath',
        [System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::Static,
        $null,
        [Type[]]@([string], [string]),
        $null
    )
    if ($relativeMethod) {
        return [System.IO.Path]::GetRelativePath($baseFull, $pathFull)
    }
    if (-not $baseFull.EndsWith([System.IO.Path]::DirectorySeparatorChar) -and
        -not $baseFull.EndsWith([System.IO.Path]::AltDirectorySeparatorChar)) {
        $baseFull += [System.IO.Path]::DirectorySeparatorChar
    }
    $baseUri = [System.Uri]$baseFull
    $pathUri = [System.Uri]$pathFull
    $relativeUri = $baseUri.MakeRelativeUri($pathUri)
    $relative = [System.Uri]::UnescapeDataString($relativeUri.ToString())
    return $relative.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
}

function Test-IsExcluded {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][bool]$IsDirectory
    )
    $rel = $RelativePath.Replace('\', '/')
    if ($rel.StartsWith('./')) { $rel = $rel.Substring(2) }
    while ($rel.StartsWith('/')) { $rel = $rel.Substring(1) }
    if ([string]::IsNullOrWhiteSpace($rel) -or $rel -eq '.') { return $false }
    $segments = $rel.Split('/', [System.StringSplitOptions]::RemoveEmptyEntries)

    if ($segments -contains '.git') { return $true }
    if ($segments -contains '.github') { return $true }
    if ($segments -contains 'tests') { return $true }
    if ($segments -contains 'tmp') { return $true }
    if ($segments -contains '__pycache__') { return $true }

    if (-not $IsDirectory) {
        $name = [System.IO.Path]::GetFileName($rel)
        if ($name -like '*.pyc') { return $true }
        # Strip workspace SQLite/JSONL artifacts so they never ship in install packages.
        if ($segments -contains 'workspace' -and ($name -like '*.sqlite' -or $name -like '*.jsonl')) { return $true }
        if ($name -eq 'plan.md') { return $true }
    }
    return $false
}

# ── Skills-directory copy (Claude / Codex / Antigravity / Cowork) ────────────

function Copy-Skill {
    param(
        [Parameter(Mandatory = $true)][string]$Src,
        [Parameter(Mandatory = $true)][string]$Dest,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ((Test-Path -LiteralPath $Dest) -and (-not $FORCE)) {
        Write-Warning "  $Label target already exists: $Dest`n  Use --force to overwrite."
        return
    }

    foreach ($req in $REQUIRED_PATHS) {
        $srcPath = Join-Path $Src $req
        if (-not (Test-Path -LiteralPath $srcPath)) {
            throw "Error: required skill path not found: $srcPath"
        }
    }

    $destParent = Split-Path -Path $Dest -Parent
    if ($destParent -and -not (Test-Path -LiteralPath $destParent)) {
        New-Item -ItemType Directory -Path $destParent -Force | Out-Null
    }
    if (Test-Path -LiteralPath $Dest) {
        Remove-Item -LiteralPath $Dest -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null

    foreach ($req in $REQUIRED_PATHS) {
        $srcReq = Join-Path $Src $req
        if (Test-Path -LiteralPath $srcReq -PathType Container) {
            $destReq = Join-Path $Dest $req
            New-Item -ItemType Directory -Path $destReq -Force | Out-Null
            Get-ChildItem -LiteralPath $srcReq -Force -Recurse | ForEach-Object {
                $item = $_
                $relative = Get-RelativePathCompat -BasePath $srcReq -Path $item.FullName
                $isDir = $item.PSIsContainer
                if (Test-IsExcluded -RelativePath $relative -IsDirectory $isDir) { return }
                $targetPath = Join-Path $destReq $relative
                if ($isDir) {
                    if (-not (Test-Path -LiteralPath $targetPath)) {
                        New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
                    }
                }
                else {
                    $targetParent = Split-Path -Path $targetPath -Parent
                    if ($targetParent -and -not (Test-Path -LiteralPath $targetParent)) {
                        New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
                    }
                    Copy-Item -LiteralPath $item.FullName -Destination $targetPath -Force
                }
            }
        }
        else {
            Copy-Item -LiteralPath $srcReq -Destination (Join-Path $Dest $req) -Force
        }
    }

    Write-Host "  Installed for ${Label}: $Dest"
}

# ── Root resolution helpers ───────────────────────────────────────────────────

function Get-GlobalRootForTool {
    param([Parameter(Mandatory = $true)][string]$Tool)
    switch ($Tool) {
        'claude'      { if ($env:CLAUDE_HOME) { return $env:CLAUDE_HOME } else { return (Join-Path $HOME '.claude') } }
        'codex'       { if ($env:CODEX_HOME)  { return $env:CODEX_HOME  } else { return (Join-Path $HOME '.codex')  } }
        'antigravity' { return (Join-Path $HOME '.gemini/antigravity') }
        default       { throw "Error: unsupported tool: $Tool" }
    }
}

function Get-WorkspaceRootForTool {
    param([Parameter(Mandatory = $true)][string]$Tool)
    switch ($Tool) {
        'antigravity' {
            if ($TARGET -eq 'antigravity' -or $PROJECT_DIR_EXPLICIT -or
                (Test-Path -LiteralPath (Join-Path $PROJECT_DIR '.agent') -PathType Container)) {
                return (Join-Path $PROJECT_DIR '.agent')
            }
        }
        'claude' {
            if ($PROJECT_DIR_EXPLICIT -and
                (Test-Path -LiteralPath (Join-Path $PROJECT_DIR '.claude') -PathType Container)) {
                return (Join-Path $PROJECT_DIR '.claude')
            }
        }
        'codex' {
            if ($PROJECT_DIR_EXPLICIT -and
                (Test-Path -LiteralPath (Join-Path $PROJECT_DIR '.codex') -PathType Container)) {
                return (Join-Path $PROJECT_DIR '.codex')
            }
        }
    }
    return $null
}

function Install-ToolAuto {
    param(
        [Parameter(Mandatory = $true)][string]$Src,
        [Parameter(Mandatory = $true)][string]$Tool,
        [Parameter(Mandatory = $true)][string]$SkillName
    )
    $wsRoot = Get-WorkspaceRootForTool -Tool $Tool
    if ($wsRoot) {
        $installRoot = $wsRoot
        $label = "${Tool}-local"
    }
    else {
        $installRoot = Get-GlobalRootForTool -Tool $Tool
        $label = "${Tool}-global"
    }
    $dest = Join-Path (Join-Path $installRoot 'skills') $SkillName
    Copy-Skill -Src $Src -Dest $dest -Label $label
}

function Install-ToolGlobal {
    param(
        [Parameter(Mandatory = $true)][string]$Src,
        [Parameter(Mandatory = $true)][string]$Tool,
        [Parameter(Mandatory = $true)][string]$SkillName
    )
    $installRoot = Get-GlobalRootForTool -Tool $Tool
    $dest = Join-Path (Join-Path $installRoot 'skills') $SkillName
    Copy-Skill -Src $Src -Dest $dest -Label "${Tool}-global"
}

# ── IDE-native format installers ─────────────────────────────────────────────

# Cursor — .cursor\rules\dataset-generator.mdc  (MDC frontmatter format)
function Install-Cursor {
    param([Parameter(Mandatory = $true)][string]$Src)
    $rulesDir = Join-Path $PROJECT_DIR '.cursor/rules'
    $mdcFile  = Join-Path $rulesDir 'dataset-generator.mdc'

    if ((Test-Path -LiteralPath $mdcFile -PathType Leaf) -and (-not $FORCE)) {
        Write-Warning "  Cursor rule already exists: $mdcFile (use --force to overwrite)"
    }
    else {
        New-Item -ItemType Directory -Path $rulesDir -Force | Out-Null
        $header = @'
---
description: "AI Dataset Generator skill. Activate when the user asks to generate, normalize, verify, deduplicate, audit, or export a training dataset (SFT or DPO) from topics, URLs, reference material, web research, or existing JSONL/CSV files."
globs: []
alwaysApply: false
---

'@
        Set-Content -LiteralPath $mdcFile -Value ($header + $SKILL_INVOCATION_TEXT)
        Write-Host "  Installed Cursor rule: $mdcFile"
    }

    $dest = Join-Path (Join-Path $PROJECT_DIR '.cursor/skills') $SKILL_NAME
    try { Copy-Skill -Src $Src -Dest $dest -Label 'Cursor (.cursor/skills/)' } catch { Write-Warning "Skipped skill copy: $_" }
}

# Windsurf — .windsurf\rules\dataset-generator.md
function Install-Windsurf {
    param([Parameter(Mandatory = $true)][string]$Src)
    $rulesDir  = Join-Path $PROJECT_DIR '.windsurf/rules'
    $ruleFile  = Join-Path $rulesDir 'dataset-generator.md'

    if ((Test-Path -LiteralPath $ruleFile -PathType Leaf) -and (-not $FORCE)) {
        Write-Warning "  Windsurf rule already exists: $ruleFile (use --force to overwrite)"
    }
    else {
        New-Item -ItemType Directory -Path $rulesDir -Force | Out-Null
        Set-Content -LiteralPath $ruleFile -Value $SKILL_INVOCATION_TEXT
        Write-Host "  Installed Windsurf rule: $ruleFile"
    }

    $dest = Join-Path (Join-Path $PROJECT_DIR '.windsurf/skills') $SKILL_NAME
    try { Copy-Skill -Src $Src -Dest $dest -Label 'Windsurf (.windsurf/skills/)' } catch { Write-Warning "Skipped skill copy: $_" }
}

# Continue.dev — .continue\prompts\dataset-generator.prompt
function Install-Continue {
    param([Parameter(Mandatory = $true)][string]$Src)
    $promptsDir = Join-Path $PROJECT_DIR '.continue/prompts'
    $promptFile = Join-Path $promptsDir 'dataset-generator.prompt'

    if ((Test-Path -LiteralPath $promptFile -PathType Leaf) -and (-not $FORCE)) {
        Write-Warning "  Continue prompt already exists: $promptFile (use --force to overwrite)"
    }
    else {
        New-Item -ItemType Directory -Path $promptsDir -Force | Out-Null
        $promptContent = @'
name: dataset-generator
description: Run the AI Dataset Generator skill to generate, normalize, verify, deduplicate, audit, or export a training dataset.
---
You have the AI Dataset Generator skill loaded.

{{{ input }}}

Use the full dataset-generator workflow:
1. Identify the dataset task from the user's request (generate / collect / verify /
   audit / export).
2. Pick the right command surface entry (dataset generate, dataset collect,
   dataset verify, dataset audit, dataset export).
3. Run the deterministic local pipeline (Python + SQLite-backed resumable state).
4. Apply normalization, deduplication, grounding, and corpus-level audit gates.
5. Emit the final artifacts plus an auto-generated DATA_CARD.md when exporting.

Read SKILL.md for the complete multi-phase workflow.
'@
        Set-Content -LiteralPath $promptFile -Value $promptContent
        Write-Host "  Installed Continue.dev prompt: $promptFile"
    }

    $dest = Join-Path (Join-Path $PROJECT_DIR '.continue/skills') $SKILL_NAME
    try { Copy-Skill -Src $Src -Dest $dest -Label 'Continue.dev (.continue/skills/)' } catch { Write-Warning "Skipped skill copy: $_" }
}

# GitHub Copilot — .github\copilot-instructions.md
function Install-Copilot {
    param([Parameter(Mandatory = $true)][string]$Src)
    $githubDir       = Join-Path $PROJECT_DIR '.github'
    $instructionFile = Join-Path $githubDir 'copilot-instructions.md'
    New-Item -ItemType Directory -Path $githubDir -Force | Out-Null

    if (Test-Path -LiteralPath $instructionFile -PathType Leaf) {
        $existing = Get-Content -LiteralPath $instructionFile -Raw -ErrorAction SilentlyContinue
        if ($existing -like '*AI Dataset Generator Skill*') {
            Write-Host "  GitHub Copilot instructions already contain AI Dataset Generator Skill (skipping)"
        }
        else {
            Add-Content -LiteralPath $instructionFile -Value ("`n---`n`n" + $SKILL_INVOCATION_TEXT)
            Write-Host "  Updated GitHub Copilot instructions: $instructionFile"
        }
    }
    else {
        Set-Content -LiteralPath $instructionFile -Value $SKILL_INVOCATION_TEXT
        Write-Host "  Created GitHub Copilot instructions: $instructionFile"
    }

    $dest = Join-Path (Join-Path $githubDir 'skills') $SKILL_NAME
    try { Copy-Skill -Src $Src -Dest $dest -Label 'GitHub Copilot (.github/skills/)' } catch { Write-Warning "Skipped skill copy: $_" }
}

# Claude Cowork — project-scoped .claude/skills/
function Install-Cowork {
    param([Parameter(Mandatory = $true)][string]$Src)
    $dest = Join-Path (Join-Path $PROJECT_DIR '.claude/skills') $SKILL_NAME
    Copy-Skill -Src $Src -Dest $dest -Label 'Cowork (.claude/skills/)'
}

# Cline — .clinerules
function Install-Cline {
    param([Parameter(Mandatory = $true)][string]$Src)
    $rulesFile = Join-Path $PROJECT_DIR '.clinerules'
    $marker    = '<!-- ai-dataset-generator -->'

    if ((Test-Path -LiteralPath $rulesFile -PathType Leaf) -and
        ((Get-Content -LiteralPath $rulesFile -Raw) -like '*ai-dataset-generator*')) {
        if (-not $FORCE) {
            Write-Warning "  .clinerules already contains AI Dataset Generator Skill (use --force to overwrite)"
            return
        }
        else {
            $text = Get-Content -LiteralPath $rulesFile -Raw
            $text = [regex]::Replace($text, '<!-- ai-dataset-generator -->.*?<!-- /ai-dataset-generator -->\r?\n?', '', [System.Text.RegularExpressions.RegexOptions]::Singleline)
            Set-Content -LiteralPath $rulesFile -Value $text
        }
    }

    $block = "`n${marker}`n" + $SKILL_INVOCATION_TEXT + "`n<!-- /ai-dataset-generator -->`n"
    Add-Content -LiteralPath $rulesFile -Value $block
    Write-Host "  Updated .clinerules: $rulesFile"

    $dest = Join-Path (Join-Path $PROJECT_DIR '.cline/skills') $SKILL_NAME
    try { Copy-Skill -Src $Src -Dest $dest -Label 'Cline (.cline/skills/)' } catch { Write-Warning "Skipped skill copy: $_" }
}

# ── Argument parsing ──────────────────────────────────────────────────────────

$idx = 0
while ($idx -lt $args.Count) {
    $arg = $args[$idx]
    switch ($arg) {
        '--target' {
            if (($idx + 1) -ge $args.Count) { throw 'Error: missing value for --target' }
            $TARGET = $args[$idx + 1]; $TARGET_EXPLICIT = $true; $idx += 2; continue
        }
        '--project-dir' {
            if (($idx + 1) -ge $args.Count) { throw 'Error: missing value for --project-dir' }
            $PROJECT_DIR = $args[$idx + 1]; $PROJECT_DIR_EXPLICIT = $true; $idx += 2; continue
        }
        '--skill-name' {
            if (($idx + 1) -ge $args.Count) { throw 'Error: missing value for --skill-name' }
            $SKILL_NAME = $args[$idx + 1]; $idx += 2; continue
        }
        '--repo-url' {
            if (($idx + 1) -ge $args.Count) { throw 'Error: missing value for --repo-url' }
            $REPO_URL = $args[$idx + 1]; $idx += 2; continue
        }
        '--source' {
            if (($idx + 1) -ge $args.Count) { throw 'Error: missing value for --source' }
            $SOURCE_MODE = $args[$idx + 1]; $idx += 2; continue
        }
        '--repo-path' {
            if (($idx + 1) -ge $args.Count) { throw 'Error: missing value for --repo-path' }
            $REPO_PATH = $args[$idx + 1]; $idx += 2; continue
        }
        '--ref' {
            if (($idx + 1) -ge $args.Count) { throw 'Error: missing value for --ref' }
            $GITHUB_REF = $args[$idx + 1]; $idx += 2; continue
        }
        '--install-deps'       { $INSTALL_DEPS = $true; $idx += 1; continue }
        '--install-playwright' { $INSTALL_PLAYWRIGHT = $true; $INSTALL_DEPS = $true; $idx += 1; continue }
        '--online'             { $ONLINE_MODE = $true; $FORCE = $true; $idx += 1; continue }
        '--force'              { $FORCE = $true; $idx += 1; continue }
        '-h'                   { Show-Usage; exit 0 }
        '--help'               { Show-Usage; exit 0 }
        default {
            Show-Usage
            throw "Unknown option: $arg"
        }
    }
}

$VALID_TARGETS = @('claude','codex','antigravity','cowork','cursor','windsurf','continue','copilot','cline','global','project','all')
if ($TARGET -notin $VALID_TARGETS) {
    throw "Error: invalid --target: $TARGET`nValid targets: $($VALID_TARGETS -join ', ')"
}
if ($SOURCE_MODE -notin @('auto','local','remote')) {
    throw "Error: invalid --source: $SOURCE_MODE"
}
if ($ONLINE_MODE -and (-not $TARGET_EXPLICIT)) { $TARGET = 'all' }

$PY = Resolve-Python

$SCRIPT_DIR  = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$SRC_DIR     = ''
$SHOULD_CLONE = $false

# ── Source resolution ─────────────────────────────────────────────────────────

if ($ONLINE_MODE) {
    $TEMP_DIR    = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid().ToString('N'))
    $extractRoot = Join-Path $TEMP_DIR 'extracted'
    New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
    $zipPath     = Join-Path $TEMP_DIR 'package.zip'

    # Resolve a download URL. Preference order:
    #   1. Latest release asset listed by the GitHub API (any filename).
    #   2. Source archive for the latest release tag.
    #   3. Branch archive for $GITHUB_REF.
    Write-Host "Fetching latest release info from $GITHUB_REPO..."
    $downloadUrl = $null
    $downloadDesc = $null
    try {
        $releaseInfo = Invoke-RestMethod `
            -Uri "https://api.github.com/repos/$GITHUB_REPO/releases/latest" `
            -ErrorAction Stop
        $latestTag = $releaseInfo.tag_name
        if (-not [string]::IsNullOrWhiteSpace($latestTag)) {
            Write-Host "  Latest release: $latestTag"
            # Expand-Archive only handles .zip — never pick a .tar.gz asset
            # here even if one is listed first by the API.
            $asset = $releaseInfo.assets |
                Where-Object { $_.name -match '\.zip$' } |
                Select-Object -First 1
            if ($asset) {
                $downloadUrl  = $asset.browser_download_url
                $downloadDesc = "release asset: $($asset.name)"
            }
            else {
                $downloadUrl  = "https://github.com/$GITHUB_REPO/archive/refs/tags/$latestTag.zip"
                $downloadDesc = "source archive for tag $latestTag"
            }
        }
    }
    catch {
        # API call failed — fall through to branch archive below.
    }
    if (-not $downloadUrl) {
        $downloadUrl  = "https://github.com/$GITHUB_REPO/archive/refs/heads/$GITHUB_REF.zip"
        $downloadDesc = "branch archive: $GITHUB_REF"
    }
    Write-Host "  Downloading $downloadDesc..."
    Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -ErrorAction Stop

    # Expand-Archive's default error action is Continue on PS 5.1 — make it
    # fatal so a bad download surfaces here, not as "SKILL.md not found".
    Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force -ErrorAction Stop
    Remove-Item -Path $zipPath -Force

    # Locate SKILL.md. Release-asset zips may be flat (SKILL.md at the root);
    # GitHub source archives nest contents under one top-level dir like
    # `Repo-Tag/`. Support either.
    if (Test-Path -LiteralPath (Join-Path $extractRoot 'SKILL.md') -PathType Leaf) {
        $SRC_DIR = $extractRoot
    }
    else {
        $found = Get-ChildItem -LiteralPath $extractRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') -PathType Leaf } |
            Select-Object -First 1
        if (-not $found) {
            $entries = (
                Get-ChildItem -LiteralPath $extractRoot -Force -ErrorAction SilentlyContinue |
                    Select-Object -First 15 |
                    ForEach-Object { $_.Name }
            ) -join ', '
            throw "Error: downloaded archive did not contain SKILL.md.`n  Source URL: $downloadUrl`n  Extract dir: $extractRoot`n  Top-level entries: $entries"
        }
        $SRC_DIR = $found.FullName
    }
    Write-Host "Using downloaded package source: $SRC_DIR"
}
elseif (-not [string]::IsNullOrWhiteSpace($REPO_PATH)) {
    $SRC_DIR = Resolve-Dir -Dir $REPO_PATH
    Write-Host "Using repo path source: $SRC_DIR"
}
elseif ($SOURCE_MODE -eq 'local') {
    $SRC_DIR = $SCRIPT_DIR
    Write-Host "Using local source: $SRC_DIR"
}
elseif ($SOURCE_MODE -eq 'remote') {
    $SHOULD_CLONE = $true
}
elseif (Test-Path -LiteralPath (Join-Path $SCRIPT_DIR 'SKILL.md') -PathType Leaf) {
    $SRC_DIR = $SCRIPT_DIR
    Write-Host "Using local source: $SRC_DIR"
}
else {
    $SHOULD_CLONE = $true
}

try {
    if ($SHOULD_CLONE) {
        # Resolve git to its real executable (not a PS alias, not a profile
        # function) so the call operator below is guaranteed to invoke the
        # real git binary / .cmd shim.
        $gitCmd = Get-Command -Name 'git' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $gitCmd) {
            throw "Error: git executable not found on PATH. Install Git for Windows (https://git-scm.com/download/win) or pass --online to download a release archive instead."
        }
        $gitExe = $gitCmd.Source

        $TEMP_DIR = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $TEMP_DIR -Force | Out-Null
        $cloneDir = Join-Path $TEMP_DIR 'repo'
        Write-Host "Cloning source repo: $REPO_URL"
        Write-Host "  using git:   $gitExe"
        Write-Host "  destination: $cloneDir"

        # Direct invocation — git's stdout/stderr stream through to the user.
        # No wrapper function (would otherwise capture stdout into a variable
        # and leave the user wondering whether git actually ran).
        & $gitExe clone --depth 1 $REPO_URL $cloneDir
        $cloneExit = $LASTEXITCODE

        if ($cloneExit -ne 0) {
            throw "Error: git clone exited with code $cloneExit.`nTip: pass --online to download a release archive instead of cloning."
        }
        if (-not (Test-Path -LiteralPath $cloneDir -PathType Container)) {
            throw "Error: git clone reported success but did not create the destination directory: $cloneDir"
        }
        $SRC_DIR = $cloneDir
        Write-Host "Using remote source: $SRC_DIR"
    }

    if (-not (Test-Path -LiteralPath (Join-Path $SRC_DIR 'SKILL.md') -PathType Leaf)) {
        $listing = ''
        if (Test-Path -LiteralPath $SRC_DIR -PathType Container) {
            $entries = Get-ChildItem -LiteralPath $SRC_DIR -Force -ErrorAction SilentlyContinue |
                Select-Object -First 15 |
                ForEach-Object { $_.Name }
            if ($entries) { $listing = "`n  Source dir contents (first 15): $($entries -join ', ')" }
            else { $listing = "`n  Source dir is empty." }
        }
        else {
            $listing = "`n  Source dir does not exist on disk."
        }
        throw "Error: SKILL.md not found in source directory: $SRC_DIR$listing"
    }

    Write-Host ''
    Write-Host 'Installing AI Dataset Generator Skill'
    Write-Host "Target:     $TARGET"
    Write-Host "Skill name: $SKILL_NAME"
    Write-Host ''

    # ── Install per target ────────────────────────────────────────────────────

    switch ($TARGET) {
        'claude'      { Install-ToolAuto  -Src $SRC_DIR -Tool 'claude'      -SkillName $SKILL_NAME }
        'codex'       { Install-ToolAuto  -Src $SRC_DIR -Tool 'codex'       -SkillName $SKILL_NAME }
        'antigravity' { Install-ToolAuto  -Src $SRC_DIR -Tool 'antigravity' -SkillName $SKILL_NAME }
        'cowork'      { Install-Cowork    -Src $SRC_DIR }
        'cursor'      { Install-Cursor    -Src $SRC_DIR }
        'windsurf'    { Install-Windsurf  -Src $SRC_DIR }
        'continue'    { Install-Continue  -Src $SRC_DIR }
        'copilot'     { Install-Copilot   -Src $SRC_DIR }
        'cline'       { Install-Cline     -Src $SRC_DIR }
        'global' {
            try { Install-ToolGlobal -Src $SRC_DIR -Tool 'claude' -SkillName $SKILL_NAME } catch { Write-Warning "Skipped claude-global: $_" }
            try { Install-ToolGlobal -Src $SRC_DIR -Tool 'codex'  -SkillName $SKILL_NAME } catch { Write-Warning "Skipped codex-global: $_" }
        }
        'project' {
            try { Install-ToolAuto -Src $SRC_DIR -Tool 'antigravity' -SkillName $SKILL_NAME } catch { Write-Warning "Skipped antigravity: $_" }
            try { Install-Cowork   -Src $SRC_DIR }                                            catch { Write-Warning "Skipped cowork: $_" }
            try { Install-Cursor   -Src $SRC_DIR }                                            catch { Write-Warning "Skipped cursor: $_" }
            try { Install-Windsurf -Src $SRC_DIR }                                            catch { Write-Warning "Skipped windsurf: $_" }
            try { Install-Continue -Src $SRC_DIR }                                            catch { Write-Warning "Skipped continue: $_" }
            try { Install-Copilot  -Src $SRC_DIR }                                            catch { Write-Warning "Skipped copilot: $_" }
            try { Install-Cline    -Src $SRC_DIR }                                            catch { Write-Warning "Skipped cline: $_" }
        }
        'all' {
            try { Install-ToolGlobal -Src $SRC_DIR -Tool 'claude' -SkillName $SKILL_NAME }   catch { Write-Warning "Skipped claude-global: $_" }
            try { Install-ToolGlobal -Src $SRC_DIR -Tool 'codex'  -SkillName $SKILL_NAME }   catch { Write-Warning "Skipped codex-global: $_" }
            try { Install-ToolAuto -Src $SRC_DIR -Tool 'antigravity' -SkillName $SKILL_NAME } catch { Write-Warning "Skipped antigravity: $_" }
            try { Install-Cowork   -Src $SRC_DIR }                                            catch { Write-Warning "Skipped cowork: $_" }
            try { Install-Cursor   -Src $SRC_DIR }                                            catch { Write-Warning "Skipped cursor: $_" }
            try { Install-Windsurf -Src $SRC_DIR }                                            catch { Write-Warning "Skipped windsurf: $_" }
            try { Install-Continue -Src $SRC_DIR }                                            catch { Write-Warning "Skipped continue: $_" }
            try { Install-Copilot  -Src $SRC_DIR }                                            catch { Write-Warning "Skipped copilot: $_" }
            try { Install-Cline    -Src $SRC_DIR }                                            catch { Write-Warning "Skipped cline: $_" }
        }
    }

    # ── Python dependencies ───────────────────────────────────────────────────

    if ($INSTALL_DEPS) {
        Write-Host ''
        Write-Host 'Installing Python dependencies...'

        # Direct invocation so pip's progress is visible. Splat the prefix
        # args (e.g. '-3' for the `py` launcher) ahead of the pip command.
        $reqPath = Join-Path $SRC_DIR 'requirements.txt'
        $depsInstalled = $false

        if (Test-Path -LiteralPath $reqPath) {
            & $PY.Command @($PY.PrefixArgs) -m pip install --user -r $reqPath
            if ($LASTEXITCODE -eq 0) {
                Write-Host '  Installed dependencies from requirements.txt'
                $depsInstalled = $true
            }
        }
        if (-not $depsInstalled) {
            $pyCli = ($PY.Command + ' ' + ($PY.PrefixArgs -join ' ')).Trim()
            Write-Warning "  Could not auto-install Python dependencies. Install manually:`n    $pyCli -m pip install --user -r requirements.txt"
        }

        if ($INSTALL_PLAYWRIGHT) {
            $playwrightOk = $false
            & $PY.Command @($PY.PrefixArgs) -m pip install --user playwright
            if ($LASTEXITCODE -eq 0) {
                & $PY.Command @($PY.PrefixArgs) -m playwright install chromium
                $playwrightOk = ($LASTEXITCODE -eq 0)
            }
            if ($playwrightOk) {
                Write-Host '  Installed Playwright + Chromium'
            }
            else {
                $pyCli = ($PY.Command + ' ' + ($PY.PrefixArgs -join ' ')).Trim()
                Write-Warning "  Could not auto-install Playwright. Install manually:`n    $pyCli -m pip install --user playwright`n    $pyCli -m playwright install chromium"
            }
        }
    }

    Write-Host ''
    Write-Host 'Install complete.'
    Write-Host ''
    Write-Host 'Next steps:'
    Write-Host '  1. Restart your IDE/agent session to pick up the skill.'
    Write-Host "  2. Ask: 'dataset generate ""Generate a 1000-example customer support dataset""'"
    Write-Host "  3. Or:  'dataset audit workspace/my-dataset.jsonl'"
}
finally {
    if ($TEMP_DIR -and (Test-Path -LiteralPath $TEMP_DIR)) {
        Remove-Item -LiteralPath $TEMP_DIR -Recurse -Force -ErrorAction SilentlyContinue
    }
}
