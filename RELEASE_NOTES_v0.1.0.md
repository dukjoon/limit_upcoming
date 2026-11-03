# limit-upcoming v0.1.0 — Initial Release ⚡

We are thrilled to announce the initial release of **`limit-upcoming` (v0.1.0)**! 

`limit-upcoming` is a deterministic local evidence bundle generator and proactive 0-token handoff tool designed to prevent broken working trees when AI coding agents hit API quota limits (HTTP 429 or rolling subscription caps).

---

## 🚀 What's New

### 1. 0-Token Passive Usage Sensing
* **OpenAI Codex CLI Telemetry**: Passively reads `~/.codex/sessions/**/rollout-*.jsonl` in fixed reverse 256KB buffers to extract `primary` (5-hour) and `secondary` (7-day/weekly) rolling quotas.
* **Claude Code StatusLine Pipeline**: Sniffs stdin payloads via `limit-upcoming hook-statusline` and caches rate limits locally.
* **Effective Quota Metric**: Evaluates `effective_used_percent = max(primary, secondary)` to catch long-term rolling caps before API exhaustion strikes.
* **Zero Observer Overhead**: Operates 100% offline via the Python standard library with 0 LLM prompt tokens consumed.

### 2. Complete Git Working Tree Evidence Bundles
* Captures **unstaged modifications** (`git diff`) and **staged modifications** (`git diff --cached`).
* **Captures new untracked files** with full contents (which `git diff` silently ignores).
* Transparent exclusion manifest for sensitive patterns (`.env*`, `*.pem`, `*.key`), binaries, and oversized files (>100KB) recorded in `manifest.json`.
* Single self-contained markdown handoff document (`HANDOFF_BUNDLE.md`) designed for one-shot agent resumption.

### 3. Adaptive Threshold Staging Guard
* **`< 80% (SAFE)`**: Silent, zero-intervention background state.
* **`80% ~ 87% (WATCH)`**: Keeps edits atomic and avoids starting large multi-file refactors.
* **`88% ~ 92% (WARNING_PRE_LIMIT)`**: Automatically updates a rolling draft bundle in `.handoff/latest-draft/`.
* **`≥ 93% (CRITICAL_HANDOFF)`**: Freezes code modifications immediately, writes the finalized bundle, and outputs resumption instructions.

### 4. Deterministic Verification Command Recording
* Executes user-specified test or lint commands (`--verify-cmd`) with configurable timeouts.
* Faithfully captures return codes, stdout, stderr, execution duration (ms), and host environment metadata without altering outputs.

---

## 📦 Installation

```bash
# Via Git
git clone https://github.com/<your-username>/limit-upcoming.git
cd limit-upcoming
pip install -e .

# Test local entrypoint
limit-upcoming probe --compact
```

## 📄 Documentation & Links
- [Specification & Guarantees](docs/SPEC.md)
- [Resumption Experiment Protocol](docs/EXPERIMENT_PROTOCOL.md)
- [Agent Skill Guide](SKILL.md)
