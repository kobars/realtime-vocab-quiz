# ADR-010 — A playful design system of our own ("Clay") replaces the neutral look

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-010 drafted with Claude Code from web/src/styles/tokens.css and docs/spec/ui.md §1, §5 and §7; the contrast ratios are recomputed by web/src/styles/contrast.test.ts. -->

- **Status:** accepted
- **Date:** 2026-10-02

## Context

The first client used direction "Slate" (`docs/spec/ui.md` §7.1): a neutral slate surface, one indigo accent, the system font, 10 px corners and calm motion. It met every accessibility rule but did not look like a game, and the spec forbade brand colors. Every component reads its look from `web/src/styles/tokens.css` through the Tailwind theme in `web/src/styles/main.css`, so the look can change in one place, but the spec, the tokens and their tests have to change together.

## Decision

- **Our own playful design system, "Clay":** a pale violet page, white cards, a brand violet primary with a brighter violet gradient end, and mint, cyan and sun as role fills that only ever sit under dark text. Shapes are rounded (16 px controls, 24 px cards, pills), outlines are 3 px, and shadows are hard, zero-blur offsets tinted from the primary through `color-mix`, so no grey shadow is left and the dark theme follows the primary.
- **A self-hosted web font:** Nunito Variable from the `@fontsource-variable/nunito` package, the only new runtime dependency. The content security policy is `default-src 'self'`, which blocks a font host, and one variable file covers weights 500 to 800. Only the latin and latin-ext faces are declared, with `font-display: swap`. Its default figures have equal widths, so the numbers need no second font.
- **A dark theme that follows the OS:** one `@media (prefers-color-scheme: dark)` block in `tokens.css` redefines the colors. There is no toggle, and Tailwind's `dark:` variant stays bound to a `.dark` ancestor, so the components carry no `dark:` classes.
- **Motion that answers a touch:** buttons, choices and interactive cards lift and press with a spring easing, the answer feedback pops in once and the podium rises once; all of it sits behind `motion-safe:`, and the reduced-motion block zeroes every duration token. FLIP, fades and the countdown keep the standard easing.
- **Contrast is a test:** `web/src/styles/contrast.test.ts` computes the WCAG 2.x ratio of every text pair (at least 4.5:1) and of the input outline and the focus ring (at least 3:1) from `tokens.css`, in both themes, and `web/src/styles/tokens.test.ts` checks the spec table against the file.

## Alternatives considered

- **Keep Slate:** the safest contrast margins and no font download, but a look with no character for a game. Rejected.
- **A font from a font host:** no package to update, but it needs a CSP exception and a third-party request on every visit. Rejected for a self-hosted file.
- **A theme toggle stored per user:** user choice, but a second source of truth and a flash of the wrong theme before the script runs. Rejected for the OS setting.
- **Soft blurred shadows:** familiar, but grey blur reads as dirty on a violet page and needs a separate value per theme. Rejected for hard shadows tinted from the primary.

## Consequences

- About 40 kB of font files are served from the app's own origin and cached; text renders in the fallback stack until the font arrives.
- Every color has a light and a dark value, and a new token needs both rows in the spec table, or `tokens.test.ts` fails.
- The light input outline (3.14:1 on the page) and focus ring (4.37:1 on the page) pass 3:1 with less margin than Slate's; the contrast test keeps them from slipping below it.

## Amendment: dark-theme depth and one focus indicator

Testing the dark theme in a browser showed that the hard offsets did not carry over: on the near-black page a 6 to 10 px violet offset reads as a misplaced ghost box, and nested surfaces stacked them (a preview card inside the join card, a button inside both). Focus also looked doubled: controls drew a box-shadow ring with a 2 px offset on top of their own 3 px outline, and two links painted Tailwind's default white offset. The dark block now redefines the shadow tokens as a soft glow under surfaces and a 2 px edge straight down under controls, and a surface inside a card casts no shadow in either theme; the light theme keeps its hard offsets, so this narrows "hard shadows tinted from the primary" to the light theme rather than reversing it. Focus is one indicator everywhere: the page's 2 px `--ring` outline with a transparent gap, which on a control with its own outline widens over that outline (`focus-hug`), so it reads as one band whatever colour the outline has on hover or selection. An outline also stays visible in forced colors, where box-shadow rings disappear. The rule is in `docs/spec/ui.md` §7.5; `web/src/components/ui/ui.test.ts` and `web/src/styles/main.test.ts` hold the focus rule, `web/src/styles/tokens.test.ts` the dark values.

<!-- AI-ASSISTED-END -->
