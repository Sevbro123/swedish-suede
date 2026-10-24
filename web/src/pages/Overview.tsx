import { curveMonotoneX } from "@visx/curve";
import { ChartTooltip, Grid, Line, LineChart, XAxis, YAxis } from "../charts";
import { useMemo } from "react";
import { fmt, logLoss, pct, right, seasonLabel, when, type Payload } from "../data";
import { Bullets, Chip, Gloss, gridKeys, Legend, Note, Panel, ProbBar, Screen, Stat, TeamDot } from "../ui";

export function Overview({ D }: { D: Payload }) {
  const S = D.data.seasons, total = D.data.total_games;
  const test = D.experiments?.rows.filter((r) => r.period === "test") ?? [];
  const best = test.filter((r) => r.kind === "main" && r.experiment !== "baseline_a").sort((a, b) => a.log_loss - b.log_loss)[0];
  const home = test.find((r) => r.experiment === "baseline_a");
  const span = best ? String(best.seasons).split("-").map(seasonLabel).join(" to ") : "";
  const next = D.live?.upcoming.slice(0, 4) ?? [];
  const pbp = S.reduce((a, s) => a + Math.min(s.pbp_downloaded, s.games), 0);
  const sh = S.reduce((a, s) => a + Math.min(s.shifts_downloaded, s.games), 0);
  const PH: [string, "done" | "wip" | "hold"][] = [["Find the data sources", "done"], ["Build the dataset and stats", "wip"], ["Simple benchmark models", "done"],
    ["Try machine-learning models", "done"], ["Live predictions for upcoming games", "done"],
    ["Compare against betting odds", D.paper ? "wip" : "hold"]];
  const PHL = { done: ["Done", "good"], wip: ["In progress", "accent"], hold: ["On hold: no odds data", undefined] } as const;

  return (
    <Screen index="01" kicker="Overview" title="Who wins tonight"
      sub="The chance the home team wins an NHL regular-season game, from what was known before puck drop. Every model is graded on seasons it was never built on.">
      <Stat k="Best model picks the winner" v={best?.accuracy ?? null} format={{ style: "percent", minimumFractionDigits: 1 }} tone="accent"
        s={best ? `${fmt(best.n_games)} games it never saw (${span})` : "not graded yet"} />
      {home && <Stat k="Always picking home" v={home.accuracy} format={{ style: "percent", minimumFractionDigits: 1 }} s="the no-skill benchmark" />}
      {best && <Stat k="Prediction error" v={+best.log_loss} format={{ minimumFractionDigits: 3, maximumFractionDigits: 3 }} s="lower is better; a 50/50 guess scores 0.693" />}
      <Stat k="Games in the data" v={total} s={`every regular season, ${S[0]!.label} to ${S[S.length - 1]!.label}`} />

      <div className={span8}><SeasonChart D={D} /></div>
      <Panel className={span4} title="Up next" note="The model's win chance. Open one to see why."
        right={<a href="#/upcoming" className="text-[0.8125rem] font-semibold text-accent no-underline">All {D.live?.upcoming.length ?? 0}</a>}>
        {next.length ? (
          <div className="flex flex-col gap-2" onKeyDown={gridKeys}>
            {next.map((g) => (
              <a key={g.game_id} data-nav href={g.why ? `#/upcoming/${g.game_id}` : "#/upcoming"} className="tile panel-2 press block p-3 text-ink no-underline">
                <div className="flex items-center justify-between text-[0.875rem] font-bold tracking-[0.04em]">
                  <span className="flex items-center gap-1.5"><TeamDot ab={g.away} />{g.away}</span>
                  <span className="t-cap">{when(g.start_utc)}</span>
                  <span className="flex items-center gap-1.5">{g.home}<TeamDot ab={g.home} /></span>
                </div>
                <div className="mt-2"><ProbBar away={g.away} home={g.home} pHome={g.p_home} /></div>
              </a>
            ))}
          </div>
        ) : <Note>No upcoming games yet.</Note>}
      </Panel>

      <Panel className={span4} title="In plain words">
        <Bullets items={[
          "Hockey is close to a coin flip. Even good models rarely pick much more than 60% of winners.",
          "We grade the stated chances, not just the picks: games given a 70% chance should be won about 7 times in 10.",
          "Shot quality is what matters most. Knowing which players are in the lineup, and how good each one is, helps a little more, and so does each team's recent results.",
          "Still unknown: whether this beats the betting odds. Paper bets track it live, and nothing here is betting advice.",
        ]} />
      </Panel>
      <Panel className={span4} title="Progress">
        <ol className="m-0 flex list-none flex-col p-0">
          {PH.map(([name, st], i) => (
            <li key={name} className="flex items-center justify-between gap-3 border-b border-line py-2.5 text-[0.9375rem] last:border-0">
              <span><span className="num mr-2 font-mono text-[0.75rem] text-muted">{String(i + 1).padStart(2, "0")}</span>{name}</span>
              <Chip tone={PHL[st][1]}>{PHL[st][0]}</Chip>
            </li>
          ))}
        </ol>
      </Panel>
      <Panel className={span4} title="Data downloaded">
        {([["Play-by-play (every shot, goal, penalty)", pbp], ["Shift charts (who was on the ice)", sh]] as const).map(([k, c]) => (
          <div key={k} className="mb-5" data-tip={`${k}: ${fmt(c)} of ${fmt(total)} games (${pct(c / total)})`} tabIndex={0}>
            <div className="flex justify-between gap-3 text-[0.9375rem]"><span>{k}</span><span className="num text-muted">{fmt(c)} / {fmt(total)}</span></div>
            <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-surface-2 shadow-[inset_0_1px_2px_rgb(0_0_0/0.3)]">
              <div className="bar-accent h-full origin-left rounded-full" style={{ transform: `scaleX(${c / total})` }} />
            </div>
          </div>
        ))}
        <Note>Goalie stats: complete, all {S.length} seasons.</Note>
      </Panel>

      <Panel className={span6} title="What's new" note="Recent changes to the model and the site.">
        <ol className="m-0 flex list-none flex-col p-0">
          {NEWS.map(([d, t]) => (
            <li key={d + t} className="flex gap-4 border-b border-line py-2.5 text-[0.9375rem] last:border-0">
              <span className="num w-14 shrink-0 font-mono text-[0.75rem] leading-6 text-accent">{d}</span><span className="text-ink-2">{t}</span>
            </li>
          ))}
        </ol>
      </Panel>
      <Panel className={span6} title="Words used on this site">
        <Gloss items={[
          ["Prediction error", "How far the stated chances were from what happened, averaged over games (statisticians call it log loss). Lower is better."],
          ["Expected goals (xG)", "The chance a shot goes in, judged from where and how it was taken."],
          ["Test seasons", "2018-19 to 2025-26. Models are finalized before these results are looked at, so they work like an exam."],
          ["Development seasons", "2012-13 to 2017-18, used to build and tune models."],
          ["Player ratings", "How much each player helps his team's chances and limits the other team's, after accounting for who he plays with and against."],
          ["Elo rating", "A running team score that goes up after wins and down after losses, by more when the result was a surprise or the margin was big."],
          ["Paper bets", "Pretend bets on the real odds, placed only when the model's chance beats the odds' chance by 3+ points. No money is involved."],
          ["95% range", "Where a model's true score likely falls, given the luck in a few thousand games."],
          ["Upper bound", "A test that uses information only certain at puck drop (like the real starting goalie). It shows the most we could gain, not a usable model."],
        ]} />
      </Panel>
    </Screen>
  );
}

const span8 = "col-span-12 xl:col-span-8", span4 = "col-span-12 md:col-span-6 xl:col-span-4", span6 = "col-span-12 xl:col-span-6";

/** Newest first. Plain words: this is the reader-facing changelog. */
const NEWS: [string, string][] = [
  ["Oct 24", "App-style redesign: full-width screens, a game-menu sidebar with keyboard controls, more depth, and team colors that recolor everything including win bars and charts."],
  ["Oct 24", "New look: the whole site was rebuilt with a cleaner design, smoother transitions, new charts and a tab bar on phones."],
  ["Oct 24", "The model now also uses each team's Elo rating, built from its wins, losses and goal margins. It was the biggest single improvement since lineups."],
  ["Oct 22", "Paper bets now stake more when the edge is bigger (1, 2 or 3 units), and a small daily parlay joins the strongest picks."],
  ["Oct 22", "Tested whether players or goalies on a hot streak win more. Streaks barely carry over, so the model ignores them."],
  ["Oct 21", "Paper trading started: pretend bets against real moneyline odds, tracked on the Paper bets page."],
  ["Oct 21", "Player ratings added: each player's effect on shot quality for and against, adjusted for teammates and opponents."],
  ["Oct 21", "Predictions update the minute a team posts its lineup, instead of at fixed times."],
  ["Oct 20", "Each upcoming game opens a page showing what pushes the prediction toward either team."],
];

/** Live model vs always-home, season by season, from the graded game rows. */
function SeasonChart({ D }: { D: Payload }) {
  const rows = useMemo(() => {
    if (!D.predictions) return [];
    const by = new Map<number, { p: number; y: number }[]>();
    for (const r of D.predictions.rows) { const a = by.get(r[1]) ?? []; a.push({ p: r[4], y: r[5] }); by.set(r[1], a); }
    return [...by].sort((a, b) => a[0] - b[0]).filter(([, g]) => g.length >= 40).map(([s, g]) => ({
      date: new Date(Math.floor(s / 10000), 9, 1), label: seasonLabel(s), n: g.length,
      model: 100 * g.filter((x) => right(x.p, x.y)).length / g.length - 50, home: 100 * g.filter((x) => x.y).length / g.length - 50, ll: logLoss(g),
    }));
  }, [D.predictions]);
  if (rows.length < 2) return null;
  const labels = rows.map((r) => r.label);
  return (
    <Panel className="h-full" title="Season by season" note="Share of winners picked by the live model vs always picking home. Anchored at a coin flip (50%). Each season is graded by a model built only on earlier games."
      right={<Legend items={[["var(--home)", "Live model"], ["var(--neutral)", "Always home"]]} />}>
      <LineChart data={rows} aspectRatio="2 / 1" margin={{ top: 16, right: 12, bottom: 40, left: 40 }}>
        <Grid horizontal numTicksRows={4} />
        <Line dataKey="model" stroke="var(--home)" curve={curveMonotoneX} fadeEdges={false} />
        <Line dataKey="home" stroke="var(--neutral)" strokeWidth={2} curve={curveMonotoneX} fadeEdges={false} />
        <YAxis numTicks={4} formatValue={(v) => `${(v + 50).toFixed(0)}%`} />
        <XAxis tickMode="data" labels={labels} numTicks={{ base: 4, md: rows.length }} />
        <ChartTooltip dateLabels={labels} rows={(p) => [
          { color: "var(--home)", label: "Live model", value: `${(p.model as number + 50).toFixed(1)}%` },
          { color: "var(--neutral)", label: "Always home", value: `${(p.home as number + 50).toFixed(1)}%` },
          { color: "transparent", label: "Prediction error", value: (p.ll as number).toFixed(3) },
          { color: "transparent", label: "Games", value: fmt(p.n as number) },
        ]} />
      </LineChart>
      <Note>The latest season is still being played, so its numbers move a lot from week to week.</Note>
    </Panel>
  );
}
