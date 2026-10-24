// The payload report/build.py embeds in the page. Field names match build.py.

export type Kind = "main" | "upper" | "detail";
export interface Season { season: number; label: string; games: number; pbp_downloaded: number; shifts_downloaded: number; processed: boolean }
export interface Run {
  run_id: string; experiment: string; period: string; seasons: string; n_games: number; log_loss: number; log_loss_lo: number;
  log_loss_hi: number; accuracy: number; name: string; what: string; kind: Kind;
}
export interface Driver { label: string; group: string; fmt: string; home: number | null; away: number | null; pts: number }
export interface Why { base: number; groups: { name: string; pts: number }[]; top: Driver[]; n_inputs: number }
export interface Upcoming {
  game_id: number; start_utc: string; date: string; away: string; home: string; p_home: number; lineup: string;
  home_b2b: boolean; away_b2b: boolean; why: Why | null;
}
export interface Record_ { n: number; accuracy: number; log_loss: number; home_rate: number }
export interface Live {
  updated_at: string | null; season: number | null; label: string | null; upcoming: Upcoming[];
  season_record: Record_ | null; live_record: Record_ | null;
  recent: { date: string; away: string; home: string; p_home: number; home_win: number }[];
}
export interface Bet {
  start_utc: string; away: string; home: string; side: string; team: string; price: number; book: string; p: number | null;
  p_mkt: number | null; edge: number | null; stake: number; close: number | null; clv: number | null; lineup: string; status: string; profit: number | null;
}
export interface Parlay { date: string; legs: string; n_legs: number; decimal: number; p: number | null; p_mkt: number | null; stake: number; status: string; profit: number | null }
export interface Paper {
  summary: {
    games_priced: number; bets: number; settled: number; won: number; lost: number; open: number; parlays: number; parlays_won: number;
    parlays_settled: number; staked: number; profit: number; roi: number | null; bankroll_start: number; bankroll: number;
    flat: { staked: number; profit: number; bankroll: number; roi: number | null }; avg_edge: number | null; avg_clv: number | null;
    beat_close: number | null; curve: number[]; curve_flat: number[];
  };
  rules: { bankroll: number; min_edge: number; stake_tiers: [number, number][]; flat_stake: number; parlay: { min_edge: number; max_legs: number; stake: number } };
  since: string; books: string[]; bets: Bet[]; parlays: Parlay[];
}
/** [date, season, away, home, p_home, home_win, score] */
export type GameRow = [string, number, string, string, number, number, string];
export interface Payload {
  built_at: string; git_rev: string;
  data: { seasons: Season[]; total_games: number };
  experiments: { rows: Run[] } | null;
  live: Live | null;
  paper: Paper | null;
  predictions: { cols: string[]; rows: GameRow[] } | null;
}

export async function loadPayload(): Promise<Payload> {
  const text = document.getElementById("payload")?.textContent ?? "null";
  const d = JSON.parse(text) as Payload | null;
  if (d) return d;
  // dev server only: a payload saved by hand to web/public/dev-payload.json (see README, Front end)
  return (await fetch("/dev-payload.json")).json();
}

// ---------- formatting ----------
export const pct = (x: number | null | undefined, d = 1) => (x == null ? "-" : `${(100 * x).toFixed(d)}%`);
export const fmt = (n: number) => Number(n).toLocaleString();
export const signed = (v: number | null | undefined, d = 2) => (v == null ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`);
export const ml = (v: number) => `${v > 0 ? "+" : ""}${v}`;
export const seasonLabel = (s: number | string) => `${String(s).slice(0, 4)}-${String(s).slice(6, 8)}`;
export const when = (iso: string) =>
  new Date(iso).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
export const day = (iso: string) => new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" });

/** Picked the winner: the side given at least 50% won (same rule as report/build.py). */
export const right = (pHome: number, homeWin: number) => (pHome >= 0.5) === (homeWin === 1);
export const logLoss = (rows: { p: number; y: number }[]) =>
  rows.reduce((a, r) => a - Math.log(Math.min(1 - 1e-15, Math.max(1e-15, r.y ? r.p : 1 - r.p))), 0) / rows.length;
