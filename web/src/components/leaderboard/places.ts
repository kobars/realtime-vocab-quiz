// AI-ASSISTED: the classes shared by the leaderboard rows, the pinned row and the podium: the rank chip and the fills of the first three places.
/** First place on sun, second on a silver tint, third on a bronze tint, all under dark text. */
const PLACE_FILL: Record<number, string> = {
  1: 'border-night/10 bg-sun text-night',
  2: 'border-border bg-muted text-foreground',
  3: 'border-warning/25 bg-warning-soft text-foreground',
}

/** The fill of a rank: a place fill for the first three, muted for the rest. */
export const placeFill = (rank: number): string => PLACE_FILL[rank] ?? 'border-transparent bg-muted text-muted-foreground'

/** A round chip that grows with the digits of the rank. */
export const RANK_CHIP = 'flex h-8 min-w-8 shrink-0 items-center justify-center rounded-full border-2 px-2 text-sm font-extrabold tabular-nums'

/** My row: the highlight tint inside a primary clay outline. */
export const MY_ROW = 'border-clay border-primary bg-highlight font-bold'
