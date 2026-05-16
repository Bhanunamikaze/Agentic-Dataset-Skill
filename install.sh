#!/usr/bin/env bash

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Bhanunamikaze/ai-dataset-generator.git}"
GITHUB_REPO="${GITHUB_REPO:-Bhanunamikaze/ai-dataset-generator}"
GITHUB_REF="${GITHUB_REF:-main}"
SKILL_NAME="dataset-generator"
TARGET="claude"
TARGET_EXPLICIT=0
PROJECT_DIR="$(pwd)"
PROJECT_DIR_EXPLICIT=0
FORCE=0
INSTALL_DEPS=0
INSTALL_PLAYWRIGHT=0
ONLINE_MODE=0
SOURCE_MODE="auto"
REPO_PATH=""
TEMP_DIR=""

# Payload paths copied into each install destination.
# docs/ and tests/ are intentionally excluded — docs/ only holds README
# screenshots, and tests/ is for repository CI rather than installed skills.
REQUIRED_PATHS=(
    "SKILL.md"
    "scripts"
    "resources"
    "sub-skills"
)

usage() {
    cat <<'EOF'
AI Dataset Generator Skill Installer

Installs the dataset-generator skill for AI coding assistants and agent IDEs.

Each IDE target installs the skill in that IDE's native format:
  claude / codex / antigravity  ->  skills/ directory  (native skill support)
  cowork                        ->  .claude/skills/   (project-scoped; commit to git)
  cursor                        ->  .cursor/rules/dataset-generator.mdc  (Cursor MDC rule)
  windsurf                      ->  .windsurf/rules/dataset-generator.md (Windsurf rule)
  copilot                       ->  .github/copilot-instructions.md
  cline                         ->  .clinerules       (Cline project instructions)
  continue                      ->  .continue/prompts/dataset-generator.prompt (slash command)

Usage:
  bash install.sh [options]

Options:
  --target <target>
      Install target (default: claude). Valid targets:
        claude       -> ~/.claude/skills/dataset-generator
        codex        -> ~/.codex/skills/dataset-generator
        antigravity  -> <project>/.agent/skills/dataset-generator
        cowork       -> <project>/.claude/skills/dataset-generator  (project-scoped, commit to git)
        cursor       -> <project>/.cursor/rules/dataset-generator.mdc
        windsurf     -> <project>/.windsurf/rules/dataset-generator.md
        continue     -> <project>/.continue/prompts/dataset-generator.prompt
        copilot      -> <project>/.github/copilot-instructions.md
        cline        -> <project>/.clinerules
        global       -> claude + codex (user-wide)
        project      -> antigravity + cowork + cursor + windsurf + continue + copilot + cline
        all          -> global + project (every target)

  --project-dir <path>         Project directory for project-local installs (default: cwd)
  --skill-name <name>          Installed folder name for skills-dir targets (default: dataset-generator)
  --repo-url <url>             Git URL for remote source installs
  --source <auto|local|remote> Source mode (default: auto)
  --repo-path <path>           Use a specific local checkout as the install source
  --online                     Fetch latest release archive from GitHub instead of cloning.
                               When no --target is supplied, defaults to --target all.
  --ref <branch-or-tag>        Branch / tag to fetch in --online mode (default: main)
  --install-deps               Install Python dependencies from requirements.txt
  --install-playwright         Also install Playwright + Chromium
  --force                      Overwrite an existing installed skill
  -h, --help                   Show this help

Examples:
  bash install.sh --target claude
  bash install.sh --target global
  bash install.sh --target project --project-dir /path/to/your/project
  bash install.sh --target cursor  --project-dir /path/to/your/project
  bash install.sh --target all     --project-dir /path/to/your/project
  bash install.sh --online
  bash install.sh --online --ref develop

Safer remote install:
  curl -fsSLO https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.sh
  bash install.sh --target claude
EOF
}

cleanup() {
    if [[ -n "${TEMP_DIR}" && -d "${TEMP_DIR}" ]]; then
        rm -rf "${TEMP_DIR}"
    fi
}

trap cleanup EXIT

require_cmd() {
    local cmd="$1"
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "Error: required command not found: ${cmd}" >&2
        exit 1
    fi
}

resolve_dir() {
    local dir="$1"
    if [[ ! -d "${dir}" ]]; then
        echo "Error: directory not found: ${dir}" >&2
        exit 1
    fi
    (cd "${dir}" && pwd)
}

# ── Skills-directory copy (Claude / Codex / Antigravity / Cowork) ────────────

copy_skill() {
    local src="$1"
    local dest="$2"
    local label="$3"

    if [[ -e "${dest}" && "${FORCE}" -ne 1 ]]; then
        echo "  Warning: ${label} target already exists: ${dest}" >&2
        echo "  Use --force to overwrite." >&2
        return 1
    fi

    local required_path
    for required_path in "${REQUIRED_PATHS[@]}"; do
        if [[ ! -e "${src}/${required_path}" ]]; then
            echo "  Error: required skill path not found: ${src}/${required_path}" >&2
            return 1
        fi
    done

    mkdir -p "$(dirname "${dest}")"
    if [[ -e "${dest}" ]]; then
        rm -rf "${dest}"
    fi
    mkdir -p "${dest}"

    if command -v rsync >/dev/null 2>&1; then
        local p
        for p in "${REQUIRED_PATHS[@]}"; do
            rsync -a \
                --exclude ".git/" \
                --exclude ".github/" \
                --exclude "__pycache__/" \
                --exclude "*.pyc" \
                --exclude "workspace/*.sqlite" \
                --exclude "workspace/*.jsonl" \
                --exclude "plan.md" \
                --exclude "tests/" \
                --exclude "tmp/" \
                "${src}/${p}" "${dest}/"
        done
    else
        (
            cd "${src}"
            tar \
                --exclude=".git" \
                --exclude=".git/*" \
                --exclude=".github" \
                --exclude=".github/*" \
                --exclude="__pycache__" \
                --exclude="*/__pycache__" \
                --exclude="*.pyc" \
                --exclude="workspace/*.sqlite" \
                --exclude="workspace/*.jsonl" \
                --exclude="plan.md" \
                --exclude="tests" \
                --exclude="tests/*" \
                --exclude="tmp" \
                --exclude="tmp/*" \
                -cf - \
                "${REQUIRED_PATHS[@]}"
        ) | (
            cd "${dest}"
            tar -xf -
        )
    fi

    find "${dest}" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
    find "${dest}" -type f -name "*.pyc" -delete 2>/dev/null || true
    # Strip workspace SQLite/JSONL artifacts that should never ship in an install package.
    find "${dest}" -type d -name "workspace" -print 2>/dev/null | while IFS= read -r ws; do
        find "${ws}" -type f \( -name "*.sqlite" -o -name "*.jsonl" \) -delete 2>/dev/null || true
    done

    echo "  Installed for ${label}: ${dest}"
}

# ── Root resolution helpers ───────────────────────────────────────────────────

global_root_for_tool() {
    local tool="$1"
    case "${tool}" in
        claude)      printf '%s\n' "${CLAUDE_HOME:-${HOME}/.claude}" ;;
        codex)       printf '%s\n' "${CODEX_HOME:-${HOME}/.codex}" ;;
        antigravity) printf '%s\n' "${HOME}/.gemini/antigravity" ;;
        *)           return 1 ;;
    esac
}

workspace_root_for_tool() {
    local tool="$1"
    case "${tool}" in
        antigravity)
            if [[ "${TARGET}" == "antigravity" || "${PROJECT_DIR_EXPLICIT}" -eq 1 || -d "${PROJECT_DIR}/.agent" ]]; then
                printf '%s\n' "${PROJECT_DIR}/.agent"
                return 0
            fi
            ;;
        claude)
            if [[ "${PROJECT_DIR_EXPLICIT}" -eq 1 && -d "${PROJECT_DIR}/.claude" ]]; then
                printf '%s\n' "${PROJECT_DIR}/.claude"
                return 0
            fi
            ;;
        codex)
            if [[ "${PROJECT_DIR_EXPLICIT}" -eq 1 && -d "${PROJECT_DIR}/.codex" ]]; then
                printf '%s\n' "${PROJECT_DIR}/.codex"
                return 0
            fi
            ;;
    esac
    return 1
}

install_tool_auto() {
    local tool="$1"
    local install_root="" label=""
    if install_root="$(workspace_root_for_tool "${tool}")"; then
        label="${tool}-local"
    else
        install_root="$(global_root_for_tool "${tool}")"
        label="${tool}-global"
    fi
    copy_skill "${SRC_DIR}" "${install_root}/skills/${SKILL_NAME}" "${label}"
}

install_tool_global() {
    local tool="$1"
    local global_root
    global_root="$(global_root_for_tool "${tool}")"
    copy_skill "${SRC_DIR}" "${global_root}/skills/${SKILL_NAME}" "${tool}-global"
}

# ── IDE-native format installers ─────────────────────────────────────────────

# Shared invocation summary written into IDE-specific rule / prompt files.
_skill_invocation_text() {
    cat <<'SKILL_CONTENT'
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
SKILL_CONTENT
}

# Cursor — .cursor/rules/dataset-generator.mdc  (MDC frontmatter format)
install_cursor() {
    local rules_dir="${PROJECT_DIR}/.cursor/rules"
    local mdc_file="${rules_dir}/dataset-generator.mdc"

    if [[ -f "${mdc_file}" && "${FORCE}" -ne 1 ]]; then
        echo "  Warning: Cursor rule already exists: ${mdc_file} (use --force to overwrite)"
        return 0
    fi

    mkdir -p "${rules_dir}"

    {
        cat <<'MDC_HEADER'
---
description: "AI Dataset Generator skill. Activate when the user asks to generate, normalize, verify, deduplicate, audit, or export a training dataset (SFT or DPO) from topics, URLs, reference material, web research, or existing JSONL/CSV files."
globs: []
alwaysApply: false
---
MDC_HEADER
        _skill_invocation_text
    } > "${mdc_file}"

    echo "  Installed Cursor rule: ${mdc_file}"

    copy_skill "${SRC_DIR}" "${PROJECT_DIR}/.cursor/skills/${SKILL_NAME}" "Cursor (.cursor/skills/)" || true
}

# Windsurf — .windsurf/rules/dataset-generator.md
install_windsurf() {
    local rules_dir="${PROJECT_DIR}/.windsurf/rules"
    local rule_file="${rules_dir}/dataset-generator.md"

    if [[ -f "${rule_file}" && "${FORCE}" -ne 1 ]]; then
        echo "  Warning: Windsurf rule already exists: ${rule_file} (use --force to overwrite)"
        return 0
    fi

    mkdir -p "${rules_dir}"
    _skill_invocation_text > "${rule_file}"

    echo "  Installed Windsurf rule: ${rule_file}"

    copy_skill "${SRC_DIR}" "${PROJECT_DIR}/.windsurf/skills/${SKILL_NAME}" "Windsurf (.windsurf/skills/)" || true
}

# Continue.dev — .continue/prompts/dataset-generator.prompt  (slash command format)
install_continue() {
    local prompts_dir="${PROJECT_DIR}/.continue/prompts"
    local prompt_file="${prompts_dir}/dataset-generator.prompt"

    if [[ -f "${prompt_file}" && "${FORCE}" -ne 1 ]]; then
        echo "  Warning: Continue prompt already exists: ${prompt_file} (use --force to overwrite)"
        return 0
    fi

    mkdir -p "${prompts_dir}"

    cat > "${prompt_file}" <<'PROMPT_FILE'
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
PROMPT_FILE

    echo "  Installed Continue.dev prompt: ${prompt_file}"

    copy_skill "${SRC_DIR}" "${PROJECT_DIR}/.continue/skills/${SKILL_NAME}" "Continue.dev (.continue/skills/)" || true
}

# GitHub Copilot — .github/copilot-instructions.md
install_copilot() {
    local github_dir="${PROJECT_DIR}/.github"
    local instructions_file="${github_dir}/copilot-instructions.md"
    mkdir -p "${github_dir}"

    local skill_block
    skill_block="$(
        printf '%s\n\n' '---'
        _skill_invocation_text
    )"

    if [[ -f "${instructions_file}" ]]; then
        if grep -q "AI Dataset Generator Skill" "${instructions_file}" 2>/dev/null; then
            echo "  GitHub Copilot instructions already contain AI Dataset Generator Skill (skipping)"
        else
            printf '\n%s\n' "${skill_block}" >> "${instructions_file}"
            echo "  Updated GitHub Copilot instructions: ${instructions_file}"
        fi
    else
        printf '%s\n' "${skill_block}" > "${instructions_file}"
        echo "  Created GitHub Copilot instructions: ${instructions_file}"
    fi

    copy_skill "${SRC_DIR}" "${github_dir}/skills/${SKILL_NAME}" "GitHub Copilot (.github/skills/)" || true
}

# Claude Cowork — project-scoped .claude/skills/ (shared via git with the whole team)
install_cowork() {
    copy_skill "${SRC_DIR}" "${PROJECT_DIR}/.claude/skills/${SKILL_NAME}" "Cowork (.claude/skills/)"
}

# Cline — .clinerules  (project-level instruction file)
install_cline() {
    local rules_file="${PROJECT_DIR}/.clinerules"
    local marker="<!-- ai-dataset-generator -->"

    if [[ -f "${rules_file}" ]] && grep -q "ai-dataset-generator" "${rules_file}" 2>/dev/null; then
        if [[ "${FORCE}" -ne 1 ]]; then
            echo "  Warning: .clinerules already contains AI Dataset Generator entry (use --force to overwrite)"
            return 0
        fi
        python3 -c "
import re
text = open('${rules_file}').read()
text = re.sub(r'<!-- ai-dataset-generator -->.*?<!-- /ai-dataset-generator -->\n?', '', text, flags=re.DOTALL)
open('${rules_file}', 'w').write(text)
"
    fi

    {
        printf '\n%s\n' "${marker}"
        _skill_invocation_text
        printf '<!-- /ai-dataset-generator -->\n'
    } >> "${rules_file}"

    echo "  Updated .clinerules: ${rules_file}"

    copy_skill "${SRC_DIR}" "${PROJECT_DIR}/.cline/skills/${SKILL_NAME}" "Cline (.cline/skills/)" || true
}

# ── Argument parsing ──────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)              TARGET="${2:-}"; TARGET_EXPLICIT=1; shift 2 ;;
        --project-dir)         PROJECT_DIR="${2:-}"; PROJECT_DIR_EXPLICIT=1; shift 2 ;;
        --skill-name)          SKILL_NAME="${2:-}"; shift 2 ;;
        --repo-url)            REPO_URL="${2:-}"; shift 2 ;;
        --source)              SOURCE_MODE="${2:-}"; shift 2 ;;
        --repo-path)           REPO_PATH="${2:-}"; shift 2 ;;
        --ref)                 GITHUB_REF="${2:-}"; shift 2 ;;
        --install-deps)        INSTALL_DEPS=1; shift ;;
        --install-playwright)  INSTALL_PLAYWRIGHT=1; INSTALL_DEPS=1; shift ;;
        --online)              ONLINE_MODE=1; FORCE=1; shift ;;
        --force)               FORCE=1; shift ;;
        -h|--help)             usage; exit 0 ;;
        *)                     echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

VALID_TARGETS="claude codex antigravity cowork cursor windsurf continue copilot cline global project all"
if ! echo "${VALID_TARGETS}" | grep -qw "${TARGET}"; then
    echo "Error: invalid --target: ${TARGET}" >&2
    echo "Valid targets: ${VALID_TARGETS}" >&2
    exit 1
fi

if [[ "${SOURCE_MODE}" != "auto" && "${SOURCE_MODE}" != "local" && "${SOURCE_MODE}" != "remote" ]]; then
    echo "Error: invalid --source: ${SOURCE_MODE}" >&2
    exit 1
fi

if [[ "${ONLINE_MODE}" -eq 1 && "${TARGET_EXPLICIT}" -ne 1 ]]; then
    TARGET="all"
fi

require_cmd bash
require_cmd python3

SCRIPT_PATH="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
SRC_DIR=""
SHOULD_CLONE=0

# ── Source resolution ─────────────────────────────────────────────────────────

if [[ "${ONLINE_MODE}" -eq 1 ]]; then
    require_cmd curl
    require_cmd tar
    TEMP_DIR="$(mktemp -d)"
    EXTRACT_DIR="${TEMP_DIR}/extracted"
    mkdir -p "${EXTRACT_DIR}"
    PKG="${TEMP_DIR}/package"

    # Resolve a download URL. Preference order:
    #   1. The first .tar.gz / .tgz asset listed on the latest release.
    #   2. The latest release source tarball (always exists for any tag).
    #   3. The configured branch archive (final fallback).
    echo "Fetching latest release info from ${GITHUB_REPO}..."
    RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/${GITHUB_REPO}/releases/latest" 2>/dev/null || true)
    LATEST_TAG=$(printf '%s' "${RELEASE_JSON}" | grep '"tag_name":' | head -n 1 | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/' || true)

    DOWNLOAD_URL=""
    DOWNLOAD_DESC=""
    if [[ -n "${LATEST_TAG}" && "${LATEST_TAG}" != "null" ]]; then
        echo "  Latest release: ${LATEST_TAG}"
        ASSET_URL=$(
            printf '%s' "${RELEASE_JSON}" \
                | grep -oE '"browser_download_url": *"[^"]+\.(tar\.gz|tgz)"' \
                | head -n 1 \
                | sed -E 's/.*"browser_download_url": *"([^"]+)".*/\1/' || true
        )
        if [[ -n "${ASSET_URL}" ]]; then
            DOWNLOAD_URL="${ASSET_URL}"
            DOWNLOAD_DESC="release asset: $(basename "${ASSET_URL}")"
        else
            DOWNLOAD_URL="https://github.com/${GITHUB_REPO}/archive/refs/tags/${LATEST_TAG}.tar.gz"
            DOWNLOAD_DESC="source archive for tag ${LATEST_TAG}"
        fi
    fi
    if [[ -z "${DOWNLOAD_URL}" ]]; then
        DOWNLOAD_URL="https://github.com/${GITHUB_REPO}/archive/refs/heads/${GITHUB_REF}.tar.gz"
        DOWNLOAD_DESC="branch archive: ${GITHUB_REF}"
    fi
    echo "  Downloading ${DOWNLOAD_DESC}..."
    if ! curl -fsSL -o "${PKG}" "${DOWNLOAD_URL}"; then
        echo "Error: download failed: ${DOWNLOAD_URL}" >&2
        exit 1
    fi
    if ! tar -xzf "${PKG}" -C "${EXTRACT_DIR}"; then
        echo "Error: extract failed for ${PKG}" >&2
        exit 1
    fi
    rm -f "${PKG}"

    # Locate SKILL.md. Release-asset tarballs may be flat (SKILL.md at root);
    # GitHub source tarballs nest contents under a single top-level dir like
    # `Repo-Tag/`. Support either.
    if [[ -f "${EXTRACT_DIR}/SKILL.md" ]]; then
        SRC_DIR="${EXTRACT_DIR}"
    else
        SRC_DIR=""
        for d in "${EXTRACT_DIR}"/*/; do
            if [[ -f "${d}SKILL.md" ]]; then
                SRC_DIR="${d%/}"
                break
            fi
        done
        if [[ -z "${SRC_DIR}" ]]; then
            echo "Error: downloaded archive did not contain SKILL.md." >&2
            echo "  Source URL: ${DOWNLOAD_URL}" >&2
            echo "  Extract dir: ${EXTRACT_DIR}" >&2
            echo "  Top-level entries:" >&2
            ls -1 "${EXTRACT_DIR}" 2>/dev/null | head -15 | sed 's/^/    /' >&2
            exit 1
        fi
    fi
    echo "Using downloaded package source: ${SRC_DIR}"
elif [[ -n "${REPO_PATH}" ]]; then
    SRC_DIR="$(resolve_dir "${REPO_PATH}")"
    echo "Using repo path source: ${SRC_DIR}"
elif [[ "${SOURCE_MODE}" == "local" ]]; then
    SRC_DIR="${SCRIPT_DIR}"
    echo "Using local source: ${SRC_DIR}"
elif [[ "${SOURCE_MODE}" == "remote" ]]; then
    SHOULD_CLONE=1
elif [[ -f "${SCRIPT_DIR}/SKILL.md" ]]; then
    SRC_DIR="${SCRIPT_DIR}"
    echo "Using local source: ${SRC_DIR}"
else
    SHOULD_CLONE=1
fi

if [[ "${SHOULD_CLONE}" -eq 1 ]]; then
    require_cmd git
    TEMP_DIR="$(mktemp -d)"
    echo "Cloning source repo: ${REPO_URL}"
    if ! git clone --depth 1 "${REPO_URL}" "${TEMP_DIR}/repo" >/dev/null 2>&1; then
        echo "Error: failed to clone source repo: ${REPO_URL}" >&2
        echo "Tip: pass --repo-path <local-path> or --online to avoid cloning." >&2
        exit 1
    fi
    SRC_DIR="${TEMP_DIR}/repo"
    echo "Using remote source: ${SRC_DIR}"
fi

if [[ ! -f "${SRC_DIR}/SKILL.md" ]]; then
    echo "Error: SKILL.md not found in source directory: ${SRC_DIR}" >&2
    exit 1
fi

echo ""
echo "Installing AI Dataset Generator Skill"
echo "Target:     ${TARGET}"
echo "Skill name: ${SKILL_NAME}"
echo ""

# ── Install per target ────────────────────────────────────────────────────────

case "${TARGET}" in
    claude)      install_tool_auto "claude" ;;
    codex)       install_tool_auto "codex" ;;
    antigravity) install_tool_auto "antigravity" ;;
    cowork)      install_cowork ;;
    cursor)      install_cursor ;;
    windsurf)    install_windsurf ;;
    continue)    install_continue ;;
    copilot)     install_copilot ;;
    cline)       install_cline ;;
    global)
        install_tool_global "claude" || true
        install_tool_global "codex"  || true
        ;;
    project)
        install_tool_auto "antigravity" || true
        install_cowork                  || true
        install_cursor                  || true
        install_windsurf                || true
        install_continue                || true
        install_copilot                 || true
        install_cline                   || true
        ;;
    all)
        install_tool_global "claude"    || true
        install_tool_global "codex"     || true
        install_tool_auto "antigravity" || true
        install_cowork                  || true
        install_cursor                  || true
        install_windsurf                || true
        install_continue                || true
        install_copilot                 || true
        install_cline                   || true
        ;;
esac

# ── Python dependencies ───────────────────────────────────────────────────────

if [[ "${INSTALL_DEPS}" -eq 1 ]]; then
    echo ""
    echo "Installing Python dependencies..."
    DEPS_OK=0
    if [[ -f "${SRC_DIR}/requirements.txt" ]] && python3 -m pip install --user -r "${SRC_DIR}/requirements.txt"; then
        echo "  Installed dependencies from requirements.txt"
        DEPS_OK=1
    else
        echo "  Warning: could not auto-install Python dependencies. Install manually:"
        echo "    python3 -m pip install --user -r requirements.txt"
    fi

    if [[ "${INSTALL_PLAYWRIGHT}" -eq 1 ]]; then
        if python3 -m pip install --user playwright && python3 -m playwright install chromium; then
            echo "  Installed Playwright + Chromium"
        else
            echo "  Warning: could not auto-install Playwright. Install manually:"
            echo "    python3 -m pip install --user playwright && python3 -m playwright install chromium"
        fi
    fi
fi

echo ""
echo "Install complete."
echo ""
echo "Next steps:"
echo "  1. Restart your IDE/agent session to pick up the skill."
echo "  2. Ask: 'dataset generate \"Generate a 1000-example customer support dataset\"'"
echo "  3. Or:  'dataset audit workspace/my-dataset.jsonl'"
