import { Bar, BarChart, BarXAxis, ChartTooltip, Grid, YAxis } from "../charts";
import { useMemo, useState } from "react";
import { fmt, logLoss, pct, right, seasonLabel, type GameRow, type Payload } from "../data";
import { Card, Chip, Empty, Note, Page } from "../ui";

const PER = 40;

export function Games({ D }: { D: Payload }) {
  const R = D.predictions?.rows ?? [];
  const teams = useMemo(() => [...new Set(R.flatMap((r) => [r[2], r[3]]))].sort(), [R]);
  const seasons = useMemo(() => [...new Set(R.map((r) => r[1]))].sort().reverse(), [R]);
  const [season, setSeason] = useState(String(seasons[0] ?? ""));
  const [team, setTeam] = useState("");
  const [outcome, setOutcome] = useState("");
  const [page, setPage] = useState(0);
  const F = useMemo(() => R.filter((r) => (!season || String(r[1]) === season) && (!team || r[2] === team || r[3] === team) && (() => {
    const ok = right(r[4], r[5]), winP = r[5] ? r[4] : 1 - r[4];
    return !outcome || (outcome === "right" ? ok : outcome === "wrong" ? !ok : winP < 0.35);
  })()).reverse(), [R, season, team, outcome]);
  if (!D.predictions) return <Page title="Game log"><Empty title="The game log" need="saved game-by-game predictions." /></Page>;

  const pages = Math.max(1, Math.ceil(F.length / PER)), pg = Math.min(page, pages - 1);
  const nRight = F.filter((r) => right(r[4], r[5])).length;
  const set = (f: (v: string) => void) => (e: React.ChangeEvent<HTMLSelectElement>) => { f(e.target.value); setPage(0); };

  return (
    <Page title="Game log" sub="Every game the model has been graded on: the test seasons, plus this season so far. Each chance was made using only games played before it. Pick a team or season to see how it did.">
      <div className="flex flex-wrap gap-2">
        <select className="field" aria-label="Season" value={season} onChange={set(setSeason)}>
          <option value="">All seasons</option>{seasons.map((x) => <option key={x} value={x}>{seasonLabel(x)}</option>)}
        </select>
        <select className="field" aria-label="Team" value={team} onChange={set(setTeam)}>
          <option value="">All teams</option>{teams.map((t) => <option key={t}>{t}</option>)}
        </select>
        <select className="field" aria-label="Result" value={outcome} onChange={set(setOutcome)}>
          <option value="">All results</option><option value="right">Picked right</option><option value="wrong">Picked wrong</option><option value="upset">Upsets (under 35%)</option>
        </select>
      </div>
      <p className="m-0 text-[1.0625rem] text-ink-2" aria-live="polite">
        {F.length ? <><b className="text-ink">{fmt(F.length)}</b> games: picked the winner in <b className="text-ink">{pct(nRight / F.length)}</b>, prediction error <b className="text-ink">{logLoss(F.map((r) => ({ p: r[4], y: r[5] }))).toFixed(3)}</b> (a 50/50 guess scores 0.693).</> : "No games match."}
      </p>
      {!outcome && <Calibration rows={F} />}
      <Card>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th>Date</th><th className="!text-left">Game</th><th>Final</th><th>Home win chance</th><th>Our pick</th><th>Result</th></tr></thead>
            <tbody>{F.slice(pg * PER, pg * PER + PER).map((r, i) => {
              const ok = right(r[4], r[5]);
              return (
                <tr key={i}>
                  <td className="text-muted">{r[0]}</td><td className="!text-left">{r[2]} at {r[3]}</td><td>{r[6]}</td><td>{(100 * r[4]).toFixed(0)}%</td>
                  <td>{r[4] >= 0.5 ? r[3] : r[2]} {(100 * Math.max(r[4], 1 - r[4])).toFixed(0)}%</td><td><Chip tone={ok ? "good" : "bad"}>{ok ? "Right" : "Wrong"}</Chip></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
        <div className="mt-4 flex items-center justify-between gap-3 text-[0.875rem] text-muted">
          <button type="button" disabled={pg === 0} onClick={() => setPage(pg - 1)} className="press rounded-full px-3 py-1.5 font-medium text-accent hover:bg-surface-2 disabled:text-muted disabled:opacity-50">Newer</button>
          <span className="num">Page {pg + 1} of {pages}</span>
          <button type="button" disabled={pg >= pages - 1} onClick={() => setPage(pg + 1)} className="press rounded-full px-3 py-1.5 font-medium text-accent hover:bg-surface-2 disabled:text-muted disabled:opacity-50">Older</button>
        </div>
      </Card>
    </Page>
  );
}

/** Are the stated chances honest? Games binned by the home win chance we gave, against how often home actually won. */
function Calibration({ rows }: { rows: GameRow[] }) {
  const bins = useMemo(() => {
    const out = [];
    for (let lo = 0.2; lo < 0.8 - 1e-9; lo += 0.1) {
      const g = rows.filter((r) => r[4] >= lo && r[4] < lo + 0.1);
      if (g.length >= 30) out.push({ name: `${Math.round(100 * lo)}-${Math.round(100 * lo + 10)}%`, n: g.length,
        said: (100 * g.reduce((a, r) => a + r[4], 0)) / g.length, happened: (100 * g.reduce((a, r) => a + r[5], 0)) / g.length });
    }
    return out;
  }, [rows]);
  if (bins.length < 3) return null;
  return (
    <Card title="Are the chances honest?" note="Games grouped by the home win chance we gave. When the chances are honest, each pair of bars matches.">
      <div className="mb-2 flex flex-wrap gap-4 text-[0.8125rem] text-ink-2">
        <span className="flex items-center gap-1.5"><i className="block size-2.5 rounded-[3px] bg-home" />We said (average chance)</span>
        <span className="flex items-center gap-1.5"><i className="block size-2.5 rounded-[3px] bg-away" />Home teams actually won</span>
      </div>
      <BarChart data={bins} aspectRatio="5 / 2" margin={{ top: 16, right: 8, bottom: 28, left: 40 }} barGap={0.3} animationDuration={700}>
        <Grid horizontal numTicksRows={4} />
        <Bar dataKey="said" fill="var(--home)" lineCap={4} />
        <Bar dataKey="happened" fill="var(--away)" lineCap={4} />
        <YAxis numTicks={4} formatValue={(v) => `${v.toFixed(0)}%`} />
        <BarXAxis />
        <ChartTooltip rows={(p) => [
          { color: "var(--home)", label: "We said", value: `${(p.said as number).toFixed(1)}%` },
          { color: "var(--away)", label: "Home won", value: `${(p.happened as number).toFixed(1)}%` },
          { color: "transparent", label: "Games", value: fmt(p.n as number) },
        ]} />
      </BarChart>
      <Note>Groups with fewer than 30 games are left out; they are too small to read.</Note>
    </Card>
  );
}
