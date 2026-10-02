# Clay

<!-- AI-ASSISTED: drafted with Claude Code from the package's sources, tests and docs/spec/ui.md §5 to §7. -->

Clay is the design system of the quiz client: design tokens, a Tailwind CSS v4 theme, a
self-hosted font and a small set of Vue 3 components built on shadcn-vue and reka-ui. It is the
private workspace package `@quiz/clay` (version in [package.json](package.json), changes in
[CHANGELOG.md](CHANGELOG.md)); the app in `web/` depends on it with `workspace:*`.

- [Principles](#principles)
- [Use it](#use-it)
- [Public API](#public-api)
- [Tokens](#tokens)
- [Components](#components)
- [Theming](#theming)
- [Accessibility](#accessibility)
- [Gallery](#gallery)
- [Contributing](#contributing)

## Principles

1. **Tokens are the only source of a value.** Every colour, size, radius, shadow, duration and
   easing is a CSS custom property in [src/styles/tokens.css](src/styles/tokens.css). Classes
   read them through the theme (`bg-card`, `rounded-card`, `shadow-press`, `duration-slow`); no
   component or app file names a raw hex value, pixel size or millisecond count, and tests check
   both.
2. **Choose a variant, do not override.** Components carry the Clay look, so a screen picks a
   variant or size instead of adding classes to restyle one. A look that several screens need
   becomes a variant here.
3. **Accessible by construction.** Every text pair passes WCAG AA in both themes, every control
   shows one visible focus indicator and is at least 44 × 44 px, and motion stops when the user
   asks for reduced motion. These are tests, not guidelines.
4. **One look, two themes.** The dark theme redefines tokens, never classes; components carry
   no `dark:` class.
5. **Small and owned.** The components are our own code (copied from shadcn-vue and adapted), so
   we change them here instead of waiting for an upstream release.

## Use it

The app's Tailwind entry imports Tailwind, then the theme. `source('.')` keeps Tailwind's class
scan on the app's own source; the theme adds the classes of the package's components with its own
`@source`, so the gallery and these docs add nothing to the app's CSS:

```css
/* web/src/main.css */
@import 'tailwindcss' source('.');
@import '@quiz/clay/theme.css';
```

Components come from the package entry:

```vue
<script setup lang="ts">
import { Button, Card } from '@quiz/clay'
</script>

<template>
  <Card>
    <Button variant="mint" size="lg">Start</Button>
  </Card>
</template>
```

The package ships its TypeScript and Vue sources; the app's Vite build compiles them, so there is
no build step and no `dist/` to publish.

## Public API

Only the paths in the `exports` map of [package.json](package.json) are public. ESLint stops app
code from importing anything else from the package, or the libraries it wraps.

| Import | What it gives |
|---|---|
| `@quiz/clay` | The components, their variant helpers and types (`buttonVariants`, `ButtonVariants`, `badgeVariants`, `BadgeVariants`), `toast()` and `cn()` |
| `@quiz/clay/testing` | Test helpers for consumers' own tests: `stackedFocusClasses()` finds a class that would add a second focus indicator |
| `@quiz/clay/tokens` | The token values of each theme read from `tokens.css` (`light`, `dark`, `themes`, `Tokens`) and the contrast helpers (`contrast()`, `CONTRAST_PAIRS`, `MIN_TEXT`, `MIN_NON_TEXT`) |
| `@quiz/clay/theme.css` | The Tailwind v4 theme: the tokens, the font, the theme mapping, the Clay utilities and the base styles. Import it right after `@import 'tailwindcss'` |
| `@quiz/clay/tokens.css` | The tokens alone, for a page without Tailwind |
| `@quiz/clay/fonts.css` | The `@font-face` rules of Nunito Variable alone |

`cn()` merges class names with tailwind-merge, taught the Clay utilities: without it,
`cn('border-clay', 'border-input')` would drop `border-clay` as a second border colour.

## Tokens

The full table, with every light and dark value, its use and its contrast, is
[docs/spec/ui.md §7.2](../../../docs/spec/ui.md#72-tokens-of-direction-clay); the token test
fails when `tokens.css` and that table disagree.

| Group | Tokens | Classes |
|---|---|---|
| Surfaces and text | `--background`, `--card`, `--popover`, `--foreground`, `--muted`, `--muted-foreground`, `--border` | `bg-background`, `bg-card`, `text-muted-foreground`, `border-border` |
| Brand | `--primary`, `--primary-foreground`, `--primary-hover`, `--primary-bright`, `--ring`, `--input`, `--highlight` | `bg-primary`, `text-primary`, `border-input`, `outline-ring` |
| Role fills | `--mint`, `--cyan`, `--sun`, always under `--night` text | `bg-mint`, `text-night` |
| States | `--success`, `--destructive`, `--warning`, each with `-soft` (and `--destructive-foreground`) | `text-success`, `bg-warning-soft` |
| shadcn-vue names | `--secondary`, `--accent`, `--card-foreground`, `--popover-foreground` and their pairs | as shadcn-vue uses them; `--accent` is a hover background |
| Gradients | `--gradient-primary`, `--gradient-text` | `bg-gradient-primary`, `text-gradient` |
| Type | `--font-sans`, `--font-size-title`, `--font-size-display` | `font-sans`, `text-title`, `text-display` |
| Shape | `--radius`, `--radius-card`, `--border-clay` | `rounded-sm` to `rounded-xl`, `rounded-card`, `border-clay`, `border-b-clay` |
| Depth | `--shadow-clay`, `--shadow-clay-lift`, `--shadow-press`, `--shadow-press-hover`, `--shadow-press-active`, `--shadow-inset`, `--clay-tint`, `--blob-tint` | `shadow-clay`, `shadow-press`, …, `hero-blobs` |
| Motion | `--motion-fast`, `--motion-base`, `--motion-slow`, `--motion-count`, `--motion-pop`, `--stagger`, `--ease-standard`, `--ease-spring` | `duration-fast`, `ease-spring`, `animate-pop`, `animate-rise`, `rise-delay-N`; plain `transition-*` uses `--motion-base` |

The shadow utilities fill Tailwind's shadow slot next to its ring slots, so a ring still draws on
a hovered or pressed control. Script code that needs a value reads it from `@quiz/clay/tokens`
instead of repeating it.

## Components

| Component | Variants and props | Notes |
|---|---|---|
| `Button` | `variant`: `default`, `secondary`, `outline`, `ghost`, `link`, `destructive`, `mint`; `size`: `default`, `sm`, `lg`, `icon`, `icon-lg`; `as`, `asChild` | Every size is at least 44 px tall. Filled variants lift and press behind `motion-safe:` |
| `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardAction`, `CardContent`, `CardFooter` | `Card`: `interactive` (lifts on hover), `as` (the element, `div` by default) | `CardTitle` is an `h3`. A surface inside a card is a plain element with `rounded-card border-clay` and no shadow, so offsets never stack |
| `Badge` | `variant`: `default`, `secondary`, `outline`, `mint`, `cyan`, `sun`, `success`, `destructive`, `warning`; slot `icon` | A `span`, not a control |
| `Input` | `v-model`, `defaultValue`; native attributes pass through | 48 px tall, 16 px text at every width; `aria-invalid="true"` turns the outline and its focus band `--destructive` |
| `Progress` | `modelValue`, `max` (fills against `max`, not 100) | reka-ui's `progressbar`; give it an `aria-label` |
| `Toaster`, `toast()` | vue-sonner's `ToasterProps` | Mount one `Toaster` in the app shell and call `toast.success(...)` etc. It carries its own stylesheet |

Every component sets `data-slot` on its root (and `Button` sets `data-variant` and `data-size`),
so tests and screens can find a part without depending on its classes.

## Theming

- The light theme is on `:root`. The dark theme is one `@media (prefers-color-scheme: dark)`
  block in `tokens.css` that redefines the colours, the gradients' text stops, the tints and the
  shadows, and sets `color-scheme: dark` so scrollbars and native controls follow. **It follows
  the OS; there is no toggle.**
- Tailwind's `dark:` variant is bound to a `.dark` ancestor that the app never sets, so the
  `dark:` classes of upstream shadcn-vue code stay inert.
- In dark, surfaces get a soft glow below them and controls a 2 px edge straight down instead of
  the light theme's hard offsets (ui spec §7.5).
- The motion tokens drop to `0ms` under `prefers-reduced-motion: reduce`.
- To show a theme on part of a page (as the gallery does), set the tokens that differ, and those
  that read another token (the shadows and gradients), as custom properties on that element:
  `themes.dark` from `@quiz/clay/tokens` has every value.

## Accessibility

- **Contrast.** `CONTRAST_PAIRS` lists every foreground and background pair the components draw.
  The contrast test checks each in both themes: text at least 4.5:1, outlines and the focus ring
  at least 3:1, and each stop of the text gradient as text. A new pair goes into that list.
- **Focus.** One indicator on every control: the base style's 2 px `--ring` outline, 2 px off the
  edge. A control that draws its own outline adds `focus-hug`, which turns that outline into the
  focus band. No component adds a box-shadow ring or `outline-none`; the component tests fail if
  one does.
- **Targets.** Buttons and inputs are at least 44 × 44 px; input text stays 16 px so phones do not
  zoom.
- **Motion.** Lifts, presses and entrances sit behind `motion-safe:`, and reduced motion zeroes
  every duration token, which `transition-*` and the animations read.
- **Forced colours.** The focus outline survives forced-colours mode; `text-gradient` falls back
  to the system text colour there.
- **Semantics.** Buttons are native buttons (or the element `as` names), `Progress` is a
  `progressbar` with its value and maximum, inputs pass `aria-*` attributes through, and the
  toaster is a labelled region.

## Gallery

```bash
make clay                          # from the repository root
pnpm -C web --filter @quiz/clay dev # the same
```

It serves one page on <http://localhost:5180> with every colour (and its contrast on the page
and on a card), every contrast pair, the type scale, radii, outlines, shadows, the gradient and
the motion tokens, and every component in each variant and state (rest, hover, active, focus,
disabled, invalid), in the light and the dark theme side by side. The gallery's own Tailwind
entry makes a `data-preview="hover|active|focus"` attribute turn on the matching variant, so
those states show at rest; the attribute does nothing in the app.

`make ui-check` covers the gallery: a full-page screenshot baseline at 1280 px in each colour
scheme, and an axe scan (WCAG 2.2 AA) with no sideways scroll at 320, 768 and 1280 px.

## Contributing

### Add a token

1. Add it to `:root` in `src/styles/tokens.css`, and to the dark block when its dark value
   differs.
2. Add its row to the table in `docs/spec/ui.md` §7.2 (the token test compares them).
3. Map it in `src/styles/theme.css`: a colour goes into `@theme inline` as `--color-<name>`; a
   value Tailwind has no namespace for becomes an `@utility` that reads it.
4. If a component draws it as text or as an outline on a background, add the pair to
   `CONTRAST_PAIRS` in `src/styles/contrast.ts`.
5. If it is a class `cn()` could confuse with a colour (a `border-*`, `text-*`, `bg-*`,
   `rounded-*` or `shadow-*` name), add it to the groups in `src/utils.ts`.

### Add a component

1. Start from the shadcn-vue source (the CLI reads `components.json` in this folder and writes
   under `src/components/<name>/`), then import `cn` relatively (ESLint rejects `@/` in the
   package), put the Clay look in its variants, and remove `dark:` classes and raw values.
2. Export it from `src/components/<name>/index.ts` and from `src/index.ts`.
3. Test it in `src/components/components.test.ts`: its variants render, its accessibility
   attributes, the focus and touch-target rules, and no raw value.
4. Show every variant and state in the gallery (`gallery/sections/`), then regenerate the
   gallery baselines with `make ui-baselines`.
5. Note it under "Unreleased" in [CHANGELOG.md](CHANGELOG.md).

### Checks

`make check` type-checks the package with the app and runs its Vitest project
(`pnpm -C web exec vitest run --project clay` runs it alone): the token, theme and contrast
tests and the component tests. `make ui-check` runs the gallery spec.

### Versioning

The package follows semantic versioning: a removed or renamed export, token or variant is a
major change, a new one a minor change, a fix a patch. Record each change in the changelog.
