## PR-7 — Add the UI spec: screens, states, motion, accessibility and tokens

- **Tool:** Claude Code (claude-opus-5-5)
- **Task:** Write `docs/spec/ui.md`: the screens of the Vue client, a state chart that maps every protocol message, error code and close code to a UI state, the motion and reduced-motion rules, the keyboard, focus and live-region rules, and three candidate design-token sets with one chosen direction and its tokens.
- **Prompt / interaction:** The agent worked from a written list of the required screens, motion, accessibility and style criteria plus the merged protocol and domain specs, drafted the whole spec, and computed every contrast ratio with a short script instead of estimating it.
- **What was wrong or changed:** The first draft's phase chart re-entered at the join state on every `joined`, so a reconnect during answer feedback would have dropped the player back to the intro screen; a rule now keeps the current screen when the reconnect's `joined` agrees with it. The connection chart had no way into the "Still can't connect" card although §3.7 described it; a transition after 10 failed attempts was added. The comparison table gave the dark set's lowest text contrast against the page (6.8:1) while the lower value is on cards (6.2:1); it now states the card value.
- **Verification:** `make check` (exit 0 after rebasing on `main`; runs `scripts/tests/test_check_internal.py` and `api/tests/unit/test_smoke.py`), and `scripts/check_internal.py --commits origin/main..HEAD` (exit 0). Documentation only; the UI tests come with the client, under `web/src/`.
- **Reviewed by:** Claude Code `/code-review` (high) and Codex (`gpt-6-astra`, high reasoning), after the merge; the verified findings are in the PR comment.
- **Date:** 2026-10-01
- **Phase:** design
- **Commit:** c56b392
