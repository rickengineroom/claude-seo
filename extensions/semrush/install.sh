#!/usr/bin/env bash
# Claude SEO — Semrush extension installer.
#
# Copies the seo-semrush mirror skill into ~/.claude/skills/ and the
# seo-semrush agent into ~/.claude/agents/. The Semrush MCP is a remote
# server (https://mcp.semrush.com/v1/mcp) connected via `claude mcp add`,
# so this installer does NOT write credentials — it just installs the
# skill/agent and prints the connect command.
#
# Prereq: a Semrush subscription with API units.
set -euo pipefail

main() {
    SKILL_DIR="${HOME}/.claude/skills"
    AGENT_DIR="${HOME}/.claude/agents"

    echo "════════════════════════════════════════"
    echo "║   Claude SEO — Semrush extension     ║"
    echo "════════════════════════════════════════"

    if [ ! -d "${SKILL_DIR}/seo" ]; then
        echo "✗ claude-seo base plugin not installed."
        echo "  Install it first: curl -fsSL https://raw.githubusercontent.com/AgriciDaniel/claude-seo/main/install.sh | bash"
        exit 1
    fi

    # Locate this script's directory (works for ./install.sh and curl|bash).
    SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"

    mkdir -p "${SKILL_DIR}/seo-semrush"
    cp "${SOURCE_DIR}/skills/seo-semrush/SKILL.md" "${SKILL_DIR}/seo-semrush/SKILL.md"
    echo "✓ Installed skill: ${SKILL_DIR}/seo-semrush/SKILL.md"

    mkdir -p "${AGENT_DIR}"
    # Agent ships in the repo root agents/ dir, two levels up from here.
    AGENT_SRC="${SOURCE_DIR}/../../agents/seo-semrush.md"
    if [ -f "${AGENT_SRC}" ]; then
        cp "${AGENT_SRC}" "${AGENT_DIR}/seo-semrush.md"
        echo "✓ Installed agent: ${AGENT_DIR}/seo-semrush.md"
    fi

    echo
    echo "Connect the Semrush MCP (once, if not already connected):"
    echo "  claude mcp add --transport http semrush https://mcp.semrush.com/v1/mcp"
    echo "  (then authenticate per Semrush's MCP docs)"
    echo
    echo "Done. Open a new Claude Code session and run:"
    echo "  /seo semrush overview example.com"
    echo
    echo "Full docs: extensions/semrush/docs/SEMRUSH-SETUP.md"
}

main "$@"
