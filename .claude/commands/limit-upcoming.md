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
