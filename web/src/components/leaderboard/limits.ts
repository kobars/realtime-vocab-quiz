// AI-ASSISTED: leaderboard display limits (UI spec §3.5: the rows shown; UI spec §5.1: when FLIP is skipped).
/** The live board and the results show this many standings rows; the frames still carry the server's top 50. */
export const TOP_ROWS = 10
/** More rows than this changing place in one frame swap in one step, without FLIP. */
export const MAX_MOVES = 20
/** An open "Show all players" page is read again at most this often while the standings move. */
export const PAGE_RELOAD_MS = 1_000
