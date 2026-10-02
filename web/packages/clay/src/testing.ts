// AI-ASSISTED: the `@quiz/clay/testing` entry: the one check the component tests and the app's view tests share for a second focus indicator on top of the page's focus outline.
/** The classes that would add a ring or change the focus outline: any `ring-*` or `outline-*`, with or without a variant. */
export const stackedFocusClasses = (classes: string[]): string[] => classes.filter((c) => /(^|:)(ring|outline)-/.test(c))
