# ADR-013 — The Clay design system is a workspace package with its own gallery

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-013 drafted with Claude Code from web/packages/clay, web/eslint.config.js and web/vitest.config.ts. -->

- **Status:** accepted
- **Date:** 2026-10-02

## Context

Clay ([ADR-010](010-clay-design-system.md)) lived inside the app: the tokens and the Tailwind theme in `web/src/styles/`, the components in `web/src/components/ui/`. Nothing but review stopped a screen from importing a component's internals, wrapping reka-ui itself or writing a raw colour, there was no page that showed the components and their states side by side, and the design system could not be versioned or reused apart from the app.

## Decision

- **A pnpm workspace package, `@quiz/clay`, in `web/packages/clay/`.** The workspace root stays at `web/`, so there is still one lock file and one install; the app depends on the package with `workspace:*`. The package ships its TypeScript and Vue sources and the app's Vite build compiles them, so it has no build step.
- **A typed public API through the `exports` map:** components, variant helpers and `cn()` from `@quiz/clay`, the token values and contrast helpers from `@quiz/clay/tokens`, a focus test helper from `@quiz/clay/testing`, and the theme, token and font stylesheets. ESLint's `no-restricted-imports` keeps app code on those entry points and away from the libraries the package wraps, and a guard test keeps raw colours, radii, shadows and durations out of app code.
- **Its own tests:** the token, theme, contrast and component tests run as the package's Vitest project, which the root config runs next to the app's, so `make check` covers both.
- **A gallery page instead of Storybook:** `make clay` serves one Vite page from the package with every token and every component variant and state, in light and dark side by side; hover, active and focus are shown at rest through a `data-preview` attribute that only the gallery's Tailwind entry understands. The pinned Playwright run checks it with a screenshot baseline and axe.

## Alternatives considered

- **Keep the files in the app with lint rules on paths:** no new package, but no version, no gallery of its own and no boundary the tooling knows. Rejected.
- **A separate repository published to a registry:** real reuse across products, but a release for every change while one app is its only consumer. Rejected; the package can move out later because its API is already the `exports` map.
- **Storybook for the gallery:** a familiar tool with addons, but dozens of dev dependencies, its own builder and config, and stories that duplicate what one page shows. Rejected for a Vite page that uses the same Vite, Tailwind and Vue as the app.
- **Ship a built `dist/`:** consumers need no Vue or Tailwind build, but the only consumer has both, and a build step adds a stale-output failure. Rejected.

## Consequences

- The app's screenshot baselines did not change. Its built CSS differs only by utility classes no element used, which Tailwind used to find in tests and docs: the app's entry now scans only `web/src/` without its tests, and the theme adds the package's components.
- A change to the look is made, tested and shown in one folder; `CHANGELOG.md` records it and the semantic version says whether consumers must change.
- The package's dependencies (reka-ui, vue-sonner, class-variance-authority, tailwind-merge, clsx, the font) are its own; the app no longer lists them. The web image copies the package manifest before the frozen install.
- The gallery adds two full-page baselines to the visual suite; a component change regenerates them with `make ui-baselines`.

<!-- AI-ASSISTED-END -->
