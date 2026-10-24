import { curveMonotoneX } from "@visx/curve";
import { ChartTooltip, Grid, Line, LineChart, XAxis, YAxis } from "../charts";
import { motion } from "motion/react";
import { useMemo } from "react";
import { fmt, pct, right, when, type Payload, type Upcoming } from "../data";
import { BackLink, Bullets, Card, Chip, Empty, Note, Page, ProbBar, Stat, Stats, TeamDot } from "../ui";

const ago = (iso: string | null) => {
  const h = iso ? (Date.now() - +new Date(iso)) / 36e5 : null;
  return { h, text: h == null ? "at an unknown time" : h < 1 ? `${Math.max(1, Math.round(h * 60))} min ago` : h < 48 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} days ago` };
};

function GameCard({ g, i }: { g: Upcoming; i: number }) {
  const h = Math.round(100 * g.p_home), a = 100 - h;
  const tip = `${g.away} at ${g.home}\n${g.away} win chance ${a}%\n${g.home} win chance ${h}% (home)\novertime and shootouts included`;
  const body = (
    <>
      <div className="flex justify-between gap-2 text-[0.8125rem] text-muted"><span>{when(g.start_utc)}</span><span>away at home</span></div>
      <div className="mt-3 flex items-center justify-between text-[1.375rem] font-semibold tracking-[-0.01em]">
        <span className="flex items-center gap-2"><TeamDot ab={g.away} size={12} />{g.away}</span>
        <span className="flex items-center gap-2">{g.home}<TeamDot ab={g.home} size={12} /></span>
      </div>
      <div className="mt-3"><ProbBar away={g.away} home={g.home} pHome={g.p_home} /></div>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {g.lineup === "confirmed"
          ? <Chip tone="good" tip="Both teams have posted their lineups, so the model uses the real lineup.">Lineups posted</Chip>
          : <Chip tip="Lineups usually post about an hour before puck drop. Until then the model assumes each team dresses the same players as last game.">Expected lineups</Chip>}
        {g.away_b2b && <Chip tip={`${g.away} played yesterday too.`}>{g.away} on a back-to-back</Chip>}
        {g.home_b2b && <Chip tip={`${g.home} played yesterday too.`}>{g.home} on a back-to-back</Chip>}
      </div>
      {g.why && <div className="mt-4 flex items-center gap-1 text-[0.9375rem] font-medium text-accent">Why this pick<Chevron /></div>}
    </>
  );
  const cls = "card block p-5 text-ink no-underline";
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: Math.min(i, 10) * 0.04, ease: [0.23, 1, 0.32, 1] }}>
      {g.why ? <a href={`#/upcoming/${g.game_id}`} className={`lift press ${cls}`} data-tip={tip}>{body}</a>
        : <div className={cls} data-tip={tip} tabIndex={0}>{body}</div>}
    </motion.div>
  );
}
const Chevron = () => <svg width="7" height="12" viewBox="0 0 7 12" aria-hidden><path d="M1 1l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>;

export function UpcomingPage({ D }: { D: Payload }) {
  const L = D.live;
  if (!L || !L.upcoming.length) return <Page title="Upcoming games"><Empty title="Upcoming games" need="predictions for upcoming games (run python -m nhlmodel.live)." /></Page>;
  const { h, text } = ago(L.updated_at), rec = L.season_record, live = L.live_record, lab = L.label ?? "this season";
  return (
    <Page title="Upcoming games"
      sub={<>Each team's next game, with the chance each side wins (overtime and shootouts included). {L.upcoming.some((g) => g.why) && "Open a game to see what drives its prediction. "}
        Updated <b className="font-semibold text-ink">{text}</b>{h != null && h > 36 ? ", so these may be out of date" : ""}. Times are in your time zone.</>}>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{L.upcoming.map((g, i) => <GameCard key={g.game_id} g={g} i={i} />)}</div>
      <Note>Analysis only, not betting advice. Even a 65% favorite loses about one game in three.</Note>

      {rec && <>
        <h2 className="t-title m-0 mt-6">{lab} so far</h2>
        <Stats>
          <Stat k="Picked the winner" v={rec.accuracy} format={{ style: "percent", minimumFractionDigits: 1 }} s={`${fmt(rec.n)} games played in ${lab}`} />
          <Stat k="Always picking the home team" v={rec.home_rate} format={{ style: "percent", minimumFractionDigits: 1 }} s="the no-skill benchmark, same games" />
          <Stat k="Prediction error" v={rec.log_loss} format={{ minimumFractionDigits: 3, maximumFractionDigits: 3 }} s="lower is better; a 50/50 guess scores 0.693" />
          {live && <Stat k="Logged before puck drop" v={live.accuracy} format={{ style: "percent", minimumFractionDigits: 1 }} s={`picked right in ${fmt(live.n)} games predicted live`} />}
        </Stats>
        <RunningChart D={D} />
        <div className="grid gap-6 md:grid-cols-2">
          <Card title="Latest results">
            <ul className="m-0 list-none p-0 text-[0.9375rem]">
              {L.recent.map((r, i) => {
                const fav = r.p_home >= 0.5 ? r.home : r.away, pf = Math.round(100 * Math.max(r.p_home, 1 - r.p_home)), ok = right(r.p_home, r.home_win);
                return (
                  <li key={i} className="grid grid-cols-[56px_1fr_auto_auto] items-center gap-3 border-b border-line py-2.5 last:border-0">
                    <span className="num text-[0.8125rem] text-muted">{r.date.slice(5)}</span>
                    <span>{r.away} at {r.home}</span>
                    <span className="num text-ink-2" data-tip={`we gave ${fav} ${pf}%; ${r.home_win ? r.home : r.away} won`}>{fav} {pf}%</span>
                    <Chip tone={ok ? "good" : "bad"}>{ok ? "Right" : "Wrong"}</Chip>
                  </li>
                );
              })}
            </ul>
          </Card>
          <Card title="How these are graded">
            <Bullets items={[
              "Season numbers re-create each game's prediction the way the backtests do: the model only knows games played before that month.",
              "\"Logged before puck drop\" counts predictions this site actually published before each game. It starts small and grows every day.",
              "Early in a season, a few dozen games can swing these numbers a lot. The long-run test is under Models.",
            ]} />
          </Card>
        </div>
      </>}
    </Page>
  );
}

/** This season's running record, day by day, from the graded game rows. */
function RunningChart({ D }: { D: Payload }) {
  const season = D.live?.season;
  const rows = useMemo(() => {
    const g = (D.predictions?.rows ?? []).filter((r) => r[1] === season).sort((a, b) => a[0].localeCompare(b[0]));
    const out: { date: Date; model: number; home: number; n: number }[] = [];
    let n = 0, ok = 0, hw = 0;
    g.forEach((r, i) => {
      n++; ok += +right(r[4], r[5]); hw += r[5];
      if (g[i + 1]?.[0] !== r[0] && n >= 30) out.push({ date: new Date(`${r[0]}T12:00:00`), model: (100 * ok) / n - 50, home: (100 * hw) / n - 50, n });
    });
    return out;
  }, [D.predictions, season]);
  if (rows.length < 4) return null;
  return (
    <Card title="Running record" note="Share of winners picked so far this season, after each game day (from the 30th game on), against always picking the home team. The chart is anchored at a coin flip (50%).">
      <div className="mb-2 flex flex-wrap gap-4 text-[0.8125rem] text-ink-2">
        <span className="flex items-center gap-1.5"><i className="block h-[3px] w-4 rounded-full bg-home" />Live model</span>
        <span className="flex items-center gap-1.5"><i className="block h-[3px] w-4 rounded-full bg-[#8e8e93]" />Always home</span>
      </div>
      <LineChart data={rows} aspectRatio="5 / 2" margin={{ top: 16, right: 12, bottom: 28, left: 40 }}>
        <Grid horizontal numTicksRows={4} />
        <Line dataKey="model" stroke="var(--home)" curve={curveMonotoneX} fadeEdges={false} />
        <Line dataKey="home" stroke="#8e8e93" strokeWidth={2} curve={curveMonotoneX} fadeEdges={false} />
        <YAxis numTicks={4} formatValue={(v) => `${(v + 50).toFixed(0)}%`} />
        <XAxis numTicks={5} />
        <ChartTooltip rows={(p) => [
          { color: "var(--home)", label: "Picked right", value: `${(p.model as number + 50).toFixed(1)}%` },
          { color: "#8e8e93", label: "Always home", value: `${(p.home as number + 50).toFixed(1)}%` },
          { color: "transparent", label: "Games so far", value: fmt(p.n as number) },
        ]} />
      </LineChart>
    </Card>
  );
}

const sgn = (v: number, d: number) => (v >= 0 ? "+" : "") + v.toFixed(d);
const fv = (v: number | null, f: string) => v == null ? "-" : f === "pct" ? `${(100 * v).toFixed(1)}%` : f === "pp" ? `${sgn(100 * v, 1)} pts`
  : f === "int" ? String(Math.round(v)) : f === "yesno" ? (v ? "yes" : "no") : f === "signed2" ? sgn(v, 2)
  : f === "signed1" ? sgn(v, 1) : f === "num1" ? v.toFixed(1) : v.toFixed(2);

// one upcoming game: what pushes the model toward each side (see explain() in report/build.py)
export function GameDetail({ D, id }: { D: Payload; id: string }) {
  const g = D.live?.upcoming.find((x) => String(x.game_id) === id);
  if (!g || !g.why) { location.hash = "#/upcoming"; return null; }
  const W = g.why, H = g.home, A = g.away, fav = g.p_home >= 0.5 ? H : A, top = W.groups[0];
  const say = (p: number) => (Math.abs(p) < 0.05 ? "no real pull either way" : `${Math.abs(p).toFixed(1)} points toward ${p > 0 ? H : A}`);
  const toward = (p: number) => Math.abs(p) < 0.05 ? <span className="text-muted">no pull</span>
    : <span className={`num font-medium ${p > 0 ? "text-home" : "text-away"}`}>{Math.abs(p).toFixed(1)} {p > 0 ? H : A}</span>;
  const max = Math.max(2, ...W.groups.map((x) => Math.abs(x.pts)));
  return (
    <Page back={<BackLink href="#/upcoming">Upcoming</BackLink>}
      title={<span className="flex flex-wrap items-center gap-x-3"><span className="flex items-center gap-2"><TeamDot ab={A} size={16} />{A}</span><span className="text-muted">at</span><span className="flex items-center gap-2">{H}<TeamDot ab={H} size={16} /></span></span>}
      sub={when(g.start_utc)}>
      <Card>
        <ProbBar away={A} home={H} pHome={g.p_home} big />
        <p className="m-0 mt-5 text-[1.0625rem] leading-relaxed text-ink-2">
          If these two teams were even on every stat, home ice alone would give {H} <b className="text-ink">{pct(W.base)}</b>.
          The stats move that to <b className="text-ink">{pct(g.p_home)}</b>, so the model leans {fav}.
          {top && <> The biggest factor is <b className="text-ink">{top.name.toLowerCase()}</b>: {say(top.pts)}.</>}
        </p>
      </Card>
      <Stats>
        <Stat k={`${H} win chance`} v={g.p_home} format={{ style: "percent", maximumFractionDigits: 0 }} s={`${A} ${pct(1 - g.p_home, 0)}`} />
        <Stat k="Starting point" v={W.base} format={{ style: "percent", maximumFractionDigits: 0 }} s={`${H} with home ice, teams even`} />
        <Stat k="Biggest factor" v={top?.name ?? "-"} s={top ? say(top.pts) : ""} />
        <Stat k="Lineups" v={g.lineup === "confirmed" ? "Posted" : "Expected"} s={g.lineup === "confirmed" ? "real lineups in the model" : "assumes last game's players"} />
      </Stats>

      <Card title="What moves the needle" note={`Each bar: how much ${H}'s chance would change if the teams were even on that kind of stat, in percentage points.`}>
        <div className="mb-1 grid grid-cols-[minmax(110px,190px)_1fr_96px] gap-3 text-[0.75rem] text-muted max-sm:grid-cols-[1fr_auto]">
          <span className="max-sm:hidden" /><span className="flex justify-between max-sm:col-span-2"><span className="text-away">{A}</span><span className="text-home">{H}</span></span><span className="max-sm:hidden" />
        </div>
        {W.groups.map((x, i) => (
          <div key={x.name} tabIndex={0} data-tip={`${x.name}\n${say(x.pts)}`}
            className="grid grid-cols-[minmax(110px,190px)_1fr_96px] items-center gap-x-3 gap-y-1.5 rounded-[10px] py-2 max-sm:grid-cols-[1fr_auto]">
            <span className="text-[0.9375rem]">{x.name}</span>
            <span className="relative h-3 max-sm:col-span-2 max-sm:row-start-2">
              <span className="absolute inset-y-[-4px] left-1/2 w-px bg-[var(--line-strong)]" />
              <motion.span className={`absolute inset-y-0 w-1/2 ${x.pts >= 0 ? "left-1/2 origin-left rounded-r-full bg-home" : "right-1/2 origin-right rounded-l-full bg-away"}`}
                initial={{ scaleX: 0 }} animate={{ scaleX: Math.min(1, Math.abs(x.pts) / max) }}
                transition={{ type: "spring", bounce: 0, duration: 0.6, delay: 0.05 + i * 0.04 }} />
            </span>
            <span className="text-right text-[0.875rem]">{toward(x.pts)}</span>
          </div>
        ))}
      </Card>

      <Card title="Biggest single stats">
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th>Stat</th><th>{A}</th><th>{H}</th><th>Pull</th></tr></thead>
            <tbody>{W.top.map((t, i) => (
              <tr key={i}>
                <td className="wrap">{t.label}<div className="t-cap">{t.group}</div></td>
                <td>{fv(t.away, t.fmt)}</td><td>{fv(t.home, t.fmt)}</td><td>{toward(t.pts)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Card>
      <Card title="How to read this">
        <Bullets items={[
          `The model compares the two teams on ${fmt(W.n_inputs)} stats (home minus away) and weighs each difference. These numbers come straight from that weighing for this game.`,
          "Many stats measure nearly the same thing (the same stat over 5, 10 or 20 games), so they share credit, and now and then two of them pull in opposite directions. The grouped bars are the steadier read.",
          "Points don't add up exactly, because the same stat difference moves a 50/50 game more than a lopsided one.",
        ]} />
      </Card>
    </Page>
  );
}
