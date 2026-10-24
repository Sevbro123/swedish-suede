import { curveMonotoneX } from "@visx/curve";
import { ChartTooltip, Grid, Line, LineChart, XAxis, YAxis } from "../charts";
import { useMemo } from "react";
import { fmt, logLoss, pct, right, seasonLabel, type Payload } from "../data";
import { Bullets, Card, Chip, Gloss, Note, Page, ProbBar, Stat, Stats, TeamDot } from "../ui";

export function Overview({ D }: { D: Payload }) {
  const S = D.data.seasons, total = D.data.total_games;
  const test = D.experiments?.rows.filter((r) => r.period === "test") ?? [];
  const best = test.filter((r) => r.kind === "main" && r.experiment !== "baseline_a").sort((a, b) => a.log_loss - b.log_loss)[0];
  const home = test.find((r) => r.experiment === "baseline_a");
  const span = best ? String(best.seasons).split("-").map(seasonLabel).join(" to ") : "";
  const next = D.live?.upcoming.slice(0, 3) ?? [];
  const pbp = S.reduce((a, s) => a + Math.min(s.pbp_downloaded, s.games), 0);
  const sh = S.reduce((a, s) => a + Math.min(s.shifts_downloaded, s.games), 0);
  const PH: [string, "done" | "wip" | "hold"][] = [["Find the data sources", "done"], ["Build the dataset and stats", "wip"], ["Simple benchmark models", "done"],
    ["Try machine-learning models", "done"], ["Live predictions for upcoming games", "done"],
    ["Compare against betting odds", D.paper ? "wip" : "hold"]];
  const PHL = { done: ["Done", "good"], wip: ["In progress", "accent"], hold: ["On hold: no odds data", undefined] } as const;

  return (
    <Page title={<>Who wins tonight.</>}
      sub={<>This project estimates the chance that the home team wins an NHL regular-season game, using only what was known before puck drop. Every model is graded on seasons it was never built on, so the results show how it does on games it hasn't seen.</>}>
      <Stats>
        <Stat k="Our best model picks the winner" v={best?.accuracy ?? null} format={{ style: "percent", minimumFractionDigits: 1 }}
          s={best ? `${fmt(best.n_games)} games it never saw (${span})` : "not graded yet"} />
        {home && <Stat k="Always picking the home team" v={home.accuracy} format={{ style: "percent", minimumFractionDigits: 1 }} s="the no-skill benchmark" />}
        {best && <Stat k="Prediction error" v={+best.log_loss} format={{ minimumFractionDigits: 3, maximumFractionDigits: 3 }} s="lower is better; a 50/50 guess scores 0.693" />}
        <Stat k="Games in the data" v={total} s={`every regular season, ${S[0]!.label} to ${S[S.length - 1]!.label}`} />
      </Stats>

      {next.length > 0 && (
        <Card title="Up next" note="The model's win chance for the next games. Open one to see why.">
          <div className="grid gap-3 sm:grid-cols-3">
            {next.map((g) => (
              <a key={g.game_id} href={g.why ? `#/upcoming/${g.game_id}` : "#/upcoming"} className="lift press block rounded-[14px] bg-surface-2 p-4 text-ink no-underline">
                <div className="flex items-center justify-between text-[0.9375rem] font-semibold">
                  <span className="flex items-center gap-1.5"><TeamDot ab={g.away} />{g.away}</span>
                  <span className="text-[0.75rem] font-normal text-muted">at</span>
                  <span className="flex items-center gap-1.5">{g.home}<TeamDot ab={g.home} /></span>
                </div>
                <div className="mt-3"><ProbBar away={g.away} home={g.home} pHome={g.p_home} /></div>
              </a>
            ))}
          </div>
          <a href="#/upcoming" className="mt-4 inline-block text-[0.9375rem] font-medium text-accent no-underline">All upcoming games</a>
        </Card>
      )}

      <SeasonChart D={D} />

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="In plain words">
          <Bullets items={[
            "Hockey is close to a coin flip. Even good models rarely pick much more than 60% of winners.",
            "We grade the stated chances, not just the picks: games given a 70% chance should be won about 7 times in 10.",
            "Shot quality is what matters most. Knowing which players are in the lineup helps a little more.",
            "Still unknown: whether this beats the betting odds. Paper bets track it live, and nothing here is betting advice.",
          ]} />
        </Card>
        <Card title="Progress">
          <ol className="m-0 flex list-none flex-col p-0">
            {PH.map(([name, st], i) => (
              <li key={name} className="flex items-center justify-between gap-3 border-b border-line py-2.5 text-[0.9375rem] last:border-0">
                <span><span className="num mr-2 text-muted">{i + 1}</span>{name}</span>
                <Chip tone={PHL[st][1]}>{PHL[st][0]}</Chip>
              </li>
            ))}
          </ol>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="Words used on this site">
          <Gloss items={[
            ["Prediction error", "How far the stated chances were from what happened, averaged over games (statisticians call it log loss). Lower is better."],
            ["Expected goals (xG)", "The chance a shot goes in, judged from where and how it was taken."],
            ["Test seasons", "2018-19 to 2025-26. Models are finalized before these results are looked at, so they work like an exam."],
            ["Development seasons", "2012-13 to 2017-18, used to build and tune models."],
            ["95% range", "Where a model's true score likely falls, given the luck in a few thousand games."],
            ["Upper bound", "A test that uses information only certain at puck drop (like the real starting goalie). It shows the most we could gain, not a usable model."],
          ]} />
        </Card>
        <Card title="Data downloaded">
          {([["Play-by-play (every shot, goal, penalty)", pbp], ["Shift charts (who was on the ice)", sh]] as const).map(([k, c]) => (
            <div key={k} className="mb-5" data-tip={`${k}: ${fmt(c)} of ${fmt(total)} games (${pct(c / total)})`} tabIndex={0}>
              <div className="flex justify-between gap-3 text-[0.9375rem]"><span>{k}</span><span className="num text-muted">{fmt(c)} / {fmt(total)}</span></div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2">
                <div className="h-full origin-left rounded-full bg-accent" style={{ transform: `scaleX(${c / total})` }} />
              </div>
            </div>
          ))}
          <Note>Goalie stats: complete, all {S.length} seasons.</Note>
        </Card>
      </div>
    </Page>
  );
}

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
    <Card title="Season by season" note="Share of winners picked by the live model, against always picking the home team. The chart is anchored at a coin flip (50%). Each season is graded with a model built only on earlier games.">
      <div className="mb-2 flex flex-wrap gap-4 text-[0.8125rem] text-ink-2">
        <span className="flex items-center gap-1.5"><i className="block h-[3px] w-4 rounded-full bg-home" />Live model</span>
        <span className="flex items-center gap-1.5"><i className="block h-[3px] w-4 rounded-full bg-[#8e8e93]" />Always home</span>
      </div>
      <LineChart data={rows} aspectRatio="5 / 2" margin={{ top: 16, right: 12, bottom: 28, left: 40 }}>
        <Grid horizontal numTicksRows={4} />
        <Line dataKey="model" stroke="var(--home)" curve={curveMonotoneX} fadeEdges={false} />
        <Line dataKey="home" stroke="#8e8e93" strokeWidth={2} curve={curveMonotoneX} fadeEdges={false} />
        <YAxis numTicks={4} formatValue={(v) => `${(v + 50).toFixed(0)}%`} />
        <XAxis tickMode="data" labels={labels} numTicks={{ base: 4, md: rows.length }} />
        <ChartTooltip dateLabels={labels} rows={(p) => [
          { color: "var(--home)", label: "Live model", value: `${(p.model as number + 50).toFixed(1)}%` },
          { color: "#8e8e93", label: "Always home", value: `${(p.home as number + 50).toFixed(1)}%` },
          { color: "transparent", label: "Prediction error", value: (p.ll as number).toFixed(3) },
          { color: "transparent", label: "Games", value: fmt(p.n as number) },
        ]} />
      </LineChart>
      <Note>The latest season is still being played, so its numbers move a lot from week to week.</Note>
    </Card>
  );
}
