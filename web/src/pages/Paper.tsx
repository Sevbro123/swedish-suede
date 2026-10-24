import { curveStepAfter } from "@visx/curve";
import { ChartTooltip, Grid, Line, LineChart, XAxis, YAxis } from "../charts";
import { useMemo } from "react";
import { day, ml, pct, signed, type Paper, type Payload } from "../data";
import { Card, Chip, Empty, Gloss, Note, Page, Stat, Stats } from "../ui";

const RES: Record<string, [string, "good" | "bad" | undefined]> = { won: ["Won", "good"], lost: ["Lost", "bad"], open: ["Not started", undefined], pending: ["Waiting", undefined] };
const pts = (v: number | null) => { if (v == null) return "-"; const r = Math.round(1000 * v) / 10; return `${r > 0 ? "+" : ""}${(r || 0).toFixed(1)} pts`; };

export function PaperPage({ D }: { D: Payload }) {
  const P = D.paper;
  if (!P) return <Page title="Paper bets"><Empty title="Paper bets" need="betting prices recorded before a game (each live run reads them)." /></Page>;
  const S = P.summary, R = P.rules;
  const tiers = R.stake_tiers.map(([e, u], i) => { const nx = R.stake_tiers[i + 1]; return `${u}u at ${(100 * e).toFixed(0)}${nx ? `-${(100 * nx[0]).toFixed(0)}` : "+"} points`; }).join(", ");
  return (
    <Page title="Paper bets"
      sub={<>Pretend bets, no real money. Before each game the model's win chance is compared with the betting price from the NHL's betting partner ({P.books.join(", ") || "none yet"}),
        with the bookmaker's cut taken out. When our chance for a team is at least {(100 * R.min_edge).toFixed(0)} points higher, we bet on that team at that price; anything closer is a toss-up and we sit it out.</>}>
      <Stats>
        <Stat k="Bankroll" v={S.bankroll} format={{ minimumFractionDigits: 2, maximumFractionDigits: 2 }} s={`units; started at ${S.bankroll_start}u on ${P.since}`} />
        <Stat k="Record" v={`${S.won}-${S.lost}`} s={`${S.settled} settled, ${S.open} waiting; parlays ${S.parlays_won}-${S.parlays_settled - S.parlays_won}`} />
        <Stat k="Return on stakes" v={S.roi} format={{ style: "percent", minimumFractionDigits: 1, signDisplay: "exceptZero" }} s={`${signed(S.profit)}u on ${S.staked}u staked`} />
        <Stat k="Beat the closing price" v={S.beat_close} format={{ style: "percent", maximumFractionDigits: 0 }} s={`average move ${pts(S.avg_clv)} our way`} />
      </Stats>
      <Bankroll P={P} />
      <Card title="The rules">
        <Gloss items={[
          ["Stake", <>The bigger the gap, the bigger the bet: {tiers}. A flat {R.flat_stake}u on every bet is tracked too, as a benchmark ({S.flat.bankroll.toFixed(2)}u now, {S.flat.roi == null ? "-" : pct(S.flat.roi)} return).</>],
          ["Parlay", <>When {(100 * R.parlay.min_edge).toFixed(0)}+ point picks line up on the same day, the strongest {R.parlay.max_legs > 2 ? "two or three" : "two"} also go into a {R.parlay.stake}u parlay. It pays only if every pick wins; the payout multiplies, but so does the bookmaker's cut, so it is kept small. A parlay is locked when its first game starts.</>],
          ["Edge", <>Our win chance minus the book's, after removing the bookmaker's cut. {S.bets} bets out of {S.games_priced} priced games so far, average edge {pts(S.avg_edge)}.</>],
          ["Closing price", "The last price before puck drop. If the market moved toward our side after we bet, we beat the close. Over a few hundred bets this says more than the win-loss record, which is mostly luck early on."],
          ["Timing", "Each bet is the last one made before puck drop, so it uses the confirmed lineup when it posts in time."],
          ["Unit", "A fixed bet size. Profit is shown in units, so it reads the same whatever one unit is worth."],
        ]} />
      </Card>
      <Card title="Bets">
        {P.bets.length ? (
          <div className="scroll-x">
            <table className="data">
              <thead><tr><th>Date</th><th>Game</th><th>Bet</th><th>Price</th><th>Our chance</th><th>Book's chance</th><th>Stake</th><th>Close</th><th>Moved</th><th>Result</th><th>Profit</th></tr></thead>
              <tbody>{P.bets.map((b, i) => { const r = RES[b.status] ?? [b.status, undefined]; return (
                <tr key={i}>
                  <td>{day(b.start_utc)}</td><td className="!text-left">{b.away} at {b.home}</td><td className="font-medium">{b.team}</td><td>{ml(b.price)}</td>
                  <td>{pct(b.p)}</td><td>{pct(b.p_mkt)}</td><td>{b.stake}u</td><td>{b.close == null ? "-" : ml(b.close)}</td><td>{pts(b.clv)}</td>
                  <td><Chip tone={r[1]}>{r[0]}</Chip></td><td>{b.profit == null ? "-" : signed(b.profit)}</td>
                </tr>); })}</tbody>
            </table>
          </div>
        ) : <Note>No game has cleared the {(100 * R.min_edge).toFixed(0)}-point bar yet.</Note>}
      </Card>
      <Card title="Parlays">
        {P.parlays.length ? (
          <div className="scroll-x">
            <table className="data">
              <thead><tr><th>Date</th><th>Picks</th><th>Pays</th><th>Our chance</th><th>Book's chance</th><th>Stake</th><th>Result</th><th>Profit</th></tr></thead>
              <tbody>{P.parlays.map((q, i) => { const r = RES[q.status] ?? [q.status, undefined]; return (
                <tr key={i}>
                  <td>{q.date}</td><td className="!text-left">{q.legs}</td><td>{q.decimal.toFixed(2)}x</td><td>{pct(q.p)}</td><td>{pct(q.p_mkt)}</td>
                  <td>{q.stake}u</td><td><Chip tone={r[1]}>{r[0]}</Chip></td><td>{q.profit == null ? "-" : signed(q.profit)}</td>
                </tr>); })}</tbody>
            </table>
          </div>
        ) : <Note>No day has had two {(100 * R.parlay.min_edge).toFixed(0)}+ point picks yet.</Note>}
      </Card>
      <Note>For tracking the model only. Nothing here is betting advice.</Note>
    </Page>
  );
}

/** Bankroll at the end of each day with a settled bet or parlay, for our staking and for flat stakes. */
function Bankroll({ P }: { P: Paper }) {
  const rows = useMemo(() => {
    const by = new Map<string, { ours: number; flat: number }>();
    const add = (d: string, ours: number, flat: number) => { const x = by.get(d) ?? { ours: 0, flat: 0 }; x.ours += ours; x.flat += flat; by.set(d, x); };
    for (const b of P.bets) if (b.profit != null && (b.status === "won" || b.status === "lost")) add(b.start_utc.slice(0, 10), b.profit, (b.profit / b.stake) * P.rules.flat_stake);
    for (const q of P.parlays) if (q.profit != null && (q.status === "won" || q.status === "lost")) add(q.date, q.profit, 0);
    const start = P.summary.bankroll_start, out = [{ date: new Date(`${P.since}T00:00:00`), ours: 0, flat: 0 }];
    let o = 0, f = 0;  // profit; the axis adds the starting bankroll back
    for (const [d, x] of [...by].sort()) { o += x.ours; f += x.flat; out.push({ date: new Date(`${d}T23:00:00`), ours: o, flat: f }); }
    return out;
  }, [P]);
  if (rows.length < 3) return <Card title="Bankroll"><Note>The bankroll chart starts once bets have settled on two different days.</Note></Card>;
  return (
    <Card title="Bankroll" note="Units at the end of each day with a settled bet.">
      <div className="mb-2 flex flex-wrap gap-4 text-[0.8125rem] text-ink-2">
        <span className="flex items-center gap-1.5"><i className="block h-[3px] w-4 rounded-full bg-home" />Our staking (bigger bets on bigger edges, plus parlays)</span>
        <span className="flex items-center gap-1.5"><i className="block h-[3px] w-4 rounded-full bg-[#8e8e93]" />Flat {P.rules.flat_stake}u on every bet</span>
      </div>
      <LineChart data={rows} aspectRatio="5 / 2" margin={{ top: 16, right: 12, bottom: 28, left: 44 }}>
        <Grid horizontal numTicksRows={4} highlightRowValues={[0]} />
        <Line dataKey="ours" stroke="var(--home)" curve={curveStepAfter} fadeEdges={false} />
        <Line dataKey="flat" stroke="#8e8e93" strokeWidth={2} curve={curveStepAfter} fadeEdges={false} />
        <YAxis numTicks={4} formatValue={(v) => `${(v + P.summary.bankroll_start).toFixed(1)}u`} />
        <XAxis numTicks={4} />
        <ChartTooltip rows={(p) => [
          { color: "var(--home)", label: "Our staking", value: `${(p.ours as number + P.summary.bankroll_start).toFixed(2)}u` },
          { color: "#8e8e93", label: "Flat", value: `${(p.flat as number + P.summary.bankroll_start).toFixed(2)}u` },
        ]} />
      </LineChart>
    </Card>
  );
}
