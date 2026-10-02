# Changelog

<!-- AI-ASSISTED: the changes of @quiz/clay, newest first. -->

All notable changes to `@quiz/clay` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[semantic versioning](https://semver.org/spec/v2.0.0.html) as its [README](README.md#versioning)
describes.

## [Unreleased]

## [0.1.0] - 2026-10-02

### Added

- The package itself: the Clay tokens, Tailwind v4 theme, font faces and components move out of
  the app into the workspace package `@quiz/clay`, with their tests. The app looks the same: its
  screenshot baselines are unchanged.
- The public entry points `@quiz/clay`, `@quiz/clay/tokens`, `@quiz/clay/testing`,
  `@quiz/clay/theme.css`, `@quiz/clay/tokens.css` and `@quiz/clay/fonts.css`.
- Components: `Button`, `Card` and its parts, `Badge`, `Input`, `Progress` and `Toaster`, with
  `toast()` re-exported from vue-sonner; `Toaster` brings its own stylesheet.
- `themes` (every token of each theme), `contrast()` and `CONTRAST_PAIRS` in
  `@quiz/clay/tokens`, shared by the contrast test and the gallery.
- A component gallery (`make clay`) with every token and every component variant and state in
  light and dark side by side, covered by a screenshot and axe spec.
- Component tests for rendered variants, accessibility attributes and `v-model` on `Input`.
