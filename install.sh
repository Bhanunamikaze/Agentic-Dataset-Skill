#!/usr/bin/env bash

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Bhanunamikaze/Agentic-Dataset-Skill.git}"
SKILL_NAME="dataset-generator"
TARGET="antigravity"
PROJECT_DIR="$(pwd)"
FORCE=0
INSTALL_DEPS=0
ONLINE_MODE=0
SOURCE_MODE="auto"
REPO_PATH=""
TEMP_DIR=""
REQUIRED_PATHS=(
    "SKILL.md"
    "scripts"
    "sub-skills"
    "resources"
)

usage() {
    cat <<'EOF'
Dataset Generator Skill Installer (Antigravity / Claude / Codex)

Usage:
  bash install.sh [options]

Options:
  --target <antigravity|claude|codex|global|all>
      Install target. Default: antigravity
  --project-dir <path>
      Project path for antigravity installs. Default: current directory
  --skill-name <name>
      Installed skill folder name. Default: dataset-generator
  --repo-url <url>
      Git URL used for remote source installs
  --source <auto|local|remote>
      Source mode. Default: auto
  --repo-path <path>
      Use a local repository checkout as the install source
  --install-deps
      Install optional Python dependencies for local helper scripts
  --online
      Fetch the latest release tag package instead of cloning and install globally (all IDEs).
  --force
      Overwrite an existing installed skill
  -h, --help
      Show help

Examples:
  bash install.sh --target antigravity --project-dir /path/to/project
  bash install.sh --target claude
  bash install.sh --target codex
  bash install.sh --target global
  bash install.sh --target all --project-dir /path/to/project
  bash install.sh --target codex --repo-path /path/to/Agentic-Dataset-Skill

Safer remote install:
  curl -fsSLO https://raw.githubusercontent.com/Bhanunamikaze/Agentic-Dataset-Skill/main/install.sh
  curl -fsSLO https://raw.githubusercontent.com/Bhanunamikaze/Agentic-Dataset-Skill/main/install.sh.sha256
  sha256sum -c install.sh.sha256
  bash install.sh --target codex
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

    (
        cd "${dir}"
        pwd
    )
}

copy_skill() {
    local src="$1"
    local dest="$2"
    local label="$3"

    if [[ -e "${dest}" && "${FORCE}" -ne 1 ]]; then
        echo "Error: ${label} target already exists: ${dest}" >&2
        echo "Use --force to overwrite." >&2
        exit 1
    fi

    mkdir -p "$(dirname "${dest}")"
    if [[ -e "${dest}" ]]; then
        rm -rf "${dest}"
    fi
    mkdir -p "${dest}"
    for required_path in "${REQUIRED_PATHS[@]}"; do
        if [[ ! -e "${src}/${required_path}" ]]; then
            echo "Error: required skill path not found: ${src}/${required_path}" >&2
            exit 1
        fi
    done

    if command -v rsync >/dev/null 2>&1; then
        for required_path in "${REQUIRED_PATHS[@]}"; do
            rsync -a \
                --exclude "__pycache__/" \
                --exclude "*.pyc" \
                "${src}/${required_path}" "${dest}/"
        done
    else
        (
            cd "${src}"
            tar \
                --exclude="__pycache__" \
                --exclude="*/__pycache__" \
                --exclude="*.pyc" \
                -cf - \
                "${REQUIRED_PATHS[@]}"
        ) | (
            cd "${dest}"
            tar -xf -
        )
    fi

    find "${dest}" -type d -name "__pycache__" -prune -exec rm -rf {} +
    find "${dest}" -type f -name "*.pyc" -delete
    mkdir -p "${dest}/workspace"

    echo "Installed for ${label}: ${dest}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET="${2:-}"
            shift 2
            ;;
        --project-dir)
            PROJECT_DIR="${2:-}"
            shift 2
            ;;
        --skill-name)
            SKILL_NAME="${2:-}"
            shift 2
            ;;
        --repo-url)
            REPO_URL="${2:-}"
            shift 2
            ;;
        --source)
            SOURCE_MODE="${2:-}"
            shift 2
            ;;
        --repo-path)
            REPO_PATH="${2:-}"
            shift 2
            ;;
        --install-deps)
            INSTALL_DEPS=1
            shift
            ;;
        --online)
            ONLINE_MODE=1
            TARGET="all"
            shift
            ;;
        --force)
            FORCE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
    esac
done

if [[ "${TARGET}" != "antigravity" && "${TARGET}" != "claude" && "${TARGET}" != "codex" && "${TARGET}" != "global" && "${TARGET}" != "all" ]]; then
    echo "Error: invalid --target: ${TARGET}" >&2
    exit 1
fi

if [[ "${SOURCE_MODE}" != "auto" && "${SOURCE_MODE}" != "local" && "${SOURCE_MODE}" != "remote" ]]; then
    echo "Error: invalid --source: ${SOURCE_MODE}" >&2
    exit 1
fi

require_cmd bash
require_cmd python3

SCRIPT_PATH="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
SRC_DIR=""
SHOULD_CLONE=0

if [[ "${ONLINE_MODE}" -eq 1 ]]; then
    require_cmd curl
    require_cmd tar
    echo "Fetching latest release tag..."
    LATEST_TAG=$(curl -sL https://api.github.com/repos/Bhanunamikaze/Agentic-Dataset-Skill/releases/latest | grep '"tag_name":' | head -n 1 | sed -E 's/.*"([^"]+)".*/\1/' || true)
    TEMP_DIR="$(mktemp -d)"
    if [[ -z "${LATEST_TAG}" || "${LATEST_TAG}" == "null" ]]; then
        echo "Could not determine latest tag, falling back to main branch archive..."
        curl -sL "https://github.com/Bhanunamikaze/Agentic-Dataset-Skill/archive/refs/heads/main.tar.gz" | tar -xz -C "${TEMP_DIR}" --strip-components=1
    else
        echo "Downloading latest tag package: ${LATEST_TAG}"
        curl -sL "https://github.com/Bhanunamikaze/Agentic-Dataset-Skill/archive/refs/tags/${LATEST_TAG}.tar.gz" | tar -xz -C "${TEMP_DIR}" --strip-components=1
    fi
    SRC_DIR="${TEMP_DIR}"
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
echo "Installing Dataset Generator Skill"
echo "Target: ${TARGET}"
echo "Skill name: ${SKILL_NAME}"
echo ""

if [[ "${TARGET}" == "antigravity" || "${TARGET}" == "all" ]]; then
    AG_DIR="${PROJECT_DIR}/.agent/skills/${SKILL_NAME}"
    if ! mkdir -p "$(dirname "${AG_DIR}")" 2>/dev/null; then
        echo "Warning: Skipped antigravity install. Could not write to ${PROJECT_DIR} (run from a project directory if needed)"
    else
        copy_skill "${SRC_DIR}" "${AG_DIR}" "antigravity"
    fi
fi

if [[ "${TARGET}" == "claude" || "${TARGET}" == "global" || "${TARGET}" == "all" ]]; then
    CLAUDE_DIR="${HOME}/.claude/skills/${SKILL_NAME}"
    copy_skill "${SRC_DIR}" "${CLAUDE_DIR}" "claude"
fi

if [[ "${TARGET}" == "codex" || "${TARGET}" == "global" || "${TARGET}" == "all" ]]; then
    CODEX_ROOT="${CODEX_HOME:-${HOME}/.codex}"
    CODEX_DIR="${CODEX_ROOT}/skills/${SKILL_NAME}"
    copy_skill "${SRC_DIR}" "${CODEX_DIR}" "codex"
fi

if [[ "${INSTALL_DEPS}" -eq 1 ]]; then
    echo ""
    echo "Installing optional Python dependencies..."
    if [[ -f "${SRC_DIR}/requirements.txt" ]] && python3 -m pip install --user -r "${SRC_DIR}/requirements.txt"; then
        echo "Installed dependencies from requirements.txt"
    elif python3 -m pip install --user jsonschema; then
        echo "Installed fallback dependency: jsonschema"
    else
        echo "Could not auto-install Python dependencies." >&2
        echo "Install manually: python3 -m pip install --user -r ${SRC_DIR}/requirements.txt" >&2
    fi
fi

echo ""
echo "Install complete."
echo "Next: restart your tool session to pick up the installed skill."
