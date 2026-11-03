#!/usr/bin/env bash
set -e

# ========================================================
#  ⚡ limit-upcoming One-Click Installer
# ========================================================

BOLD="\033[1m"
GREEN="\033[32m"
BLUE="\033[34m"
YELLOW="\033[33m"
CYAN="\033[36m"
RESET="\033[0m"

echo -e "${BOLD}${BLUE}⚡ Installing limit-upcoming...${RESET}"

# 1. Detect Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Error: python3 is required but not installed.${RESET}"
    exit 1
fi

PYTHON_BIN=$(command -v python3)
INSTALL_DIR="$HOME/.local/bin"
CLAUDE_CMD_DIR="$HOME/.claude/commands"
TARGET_DIR="$HOME/.limit-upcoming"

# 2. Setup standalone package directory if installed via curl
if [ -f "pyproject.toml" ] && [ -d "src/limit_upcoming" ]; then
    REPO_DIR="$(pwd)"
else
    echo -e "📦 Cloning limit-upcoming into ${TARGET_DIR}..."
    rm -rf "$TARGET_DIR"
    git clone --depth 1 "https://github.com/dukjoon/limit_upcoming.git" "$TARGET_DIR" --quiet
    REPO_DIR="$TARGET_DIR"
fi

# 3. Create standalone CLI launcher in ~/.local/bin/limit-upcoming
mkdir -p "$INSTALL_DIR" 2>/dev/null || true
LAUNCHER="$INSTALL_DIR/limit-upcoming"

cat << EOF > "$LAUNCHER"
#!/usr/bin/env bash
PYTHONPATH="${REPO_DIR}/src" exec "${PYTHON_BIN}" -m limit_upcoming.cli "\$@"
EOF
chmod +x "$LAUNCHER"
echo -e "${GREEN}✔ Installed CLI binary to:${RESET} ${BOLD}$LAUNCHER${RESET}"

# Also attempt pip editable install in background (optional)
$PYTHON_BIN -m pip install -e "${REPO_DIR}" --quiet 2>/dev/null || true

# 4. Register Slash Command for Claude Code (~/.claude/commands/limit-upcoming.md)
mkdir -p "$CLAUDE_CMD_DIR" 2>/dev/null || true
if [ -d "$CLAUDE_CMD_DIR" ]; then
    cat << 'EOF' > "$CLAUDE_CMD_DIR/limit-upcoming.md"
---
description: 0-Token local evidence bundle generator and proactive handoff guard before hitting 429 quota limits
---

When invoked, execute the following steps according to the user's intent:

1. **Check 0-Token Usage**:
   Run `limit-upcoming probe --compact` to check whether the current session is nearing rate limits.

2. **Proactive Guard (Recommended before editing files)**:
   If usage is >= 88% or you are about to start a risky multi-file edit:
   Run `limit-upcoming guard --goal "$ARGUMENTS"`

3. **Immediate Evidence Bundle**:
   If the user asks to save state, prepare a handoff, or stop work:
   Run `limit-upcoming bundle --goal "$ARGUMENTS"`
EOF
    echo -e "${GREEN}✔ Registered slash command for Claude Code:${RESET} ${BOLD}/limit-upcoming${RESET}"
fi

# 5. Register Skill for Gemini / Antigravity CLI (~/.gemini/config/skills/limit-upcoming)
GEMINI_SKILL_DIR="$HOME/.gemini/config/skills/limit-upcoming"
mkdir -p "$GEMINI_SKILL_DIR" 2>/dev/null || true
if [ -d "$GEMINI_SKILL_DIR" ] && [ -f "${REPO_DIR}/SKILL.md" ]; then
    cp "${REPO_DIR}/SKILL.md" "$GEMINI_SKILL_DIR/SKILL.md" 2>/dev/null || true
    echo -e "${GREEN}✔ Registered skill for Gemini/Antigravity CLI:${RESET} ${BOLD}/limit-upcoming${RESET}"
fi

# 6. Success Output
echo ""
echo -e "${BOLD}${GREEN}🎉 Installation Complete!${RESET}"
echo -e "--------------------------------------------------------"
echo -e "1. ${BOLD}In Claude Code / AI Agents:${RESET}"
echo -e "   Just type ${BOLD}${CYAN}/limit-upcoming${RESET} directly in the prompt!"
echo ""
echo -e "2. ${BOLD}In your Terminal (CLI):${RESET}"
echo -e "   ${BLUE}limit-upcoming probe --compact${RESET}        (Check 0-token quota)"
echo -e "   ${BLUE}limit-upcoming bundle --goal \"My Task\"${RESET}  (Create handoff bundle)"
echo "--------------------------------------------------------"

# PATH warning if ~/.local/bin is not in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo -e "${YELLOW}Note: Add ~/.local/bin to your PATH to run 'limit-upcoming' anywhere:${RESET}"
    echo -e "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
