// AI-ASSISTED: leaderboard display limits (core rules: TOP_N; UI spec §5.1: when FLIP is skipped).
/** At most this many standings rows are rendered. */
export const TOP_N = 50
/** More rows than this changing place in one frame swap in one step, without FLIP. */
export const MAX_MOVES = 20
/** An open "Show all players" page is read again at most this often while the standings move. */
export const PAGE_RELOAD_MS = 1_000
