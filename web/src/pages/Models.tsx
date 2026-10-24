import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { fmt, seasonLabel, type Payload } from "../data";
import { Card, Chip, Empty, Note, Page, Segmented } from "../ui";

const PERIOD: Record<string, string> = { test: "Test seasons", dev: "Development seasons" };

export function Models({ D }: { D: Payload }) {
  const all = D.experiments?.rows ?? [];
  const periods = [...new Set(all.map((r) => r.period))].sort().reverse();   // test first
  const [period, setPeriod] = useState(periods.includes("test") ? "test" : periods[0] ?? "");
  const [more, setMore] = useState(false);
  if (!D.experiments) return <Page title="Models"><Empty title="The model scoreboard" need="graded model results." /></Page>;

  const inPeriod = all.filter((r) => r.period === period);
  const R = inPeriod.filter((r) => more || r.kind !== "detail").sort((a, b) => a.log_loss - b.log_loss);
  const hidden = inPeriod.filter((r) => r.kind === "detail").length;
  const lo = Math.min(...R.map((r) => r.log_loss_lo)), hi = Math.max(...R.map((r) => r.log_loss_hi)), pad = (hi - lo) * 0.06;
  const a = lo - pad, b = hi + pad, x = (v: number) => `${(100 * (v - a)) / (b - a)}%`;
  const ticks = Array.from({ length: 5 }, (_, i) => a + ((b - a) * (i + 0.5)) / 5);
  const seasons = R[0] ? String(R[0].seasons).split("-").map(seasonLabel).join(" to ") : "";

  return (
    <Page title="Models"
      sub={<>Every model we tried, graded on its <b className="font-semibold text-ink">prediction error</b>: how far its stated chances were from what happened. Lower is better, and a 50/50 guess on every game scores 0.693. "Picked the winner" is shown too, but it ignores how confident each pick was.</>}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented id="period" label="Seasons" value={period} onChange={setPeriod} options={periods.map((p) => [p, PERIOD[p] ?? p])} />
        {(hidden > 0) && <button type="button" onClick={() => setMore(!more)} className="press rounded-full px-3 py-1.5 text-[0.875rem] font-medium text-accent hover:bg-surface">
          {more ? "Hide" : "Show"} {hidden} tuning and check runs</button>}
      </div>
      <Card title={`${PERIOD[period] ?? period}, ${seasons}`}
        note={`${R[0] ? fmt(R[0].n_games) : 0} games. ${period === "test" ? "These are the real exam: every model here was finalized before its test results were looked at." : "These seasons were used to build and tune the models, so their scores are a little optimistic."} Best first. The dot is each model's prediction error and the bar its 95% range; further left is better.`}>
        <div role="list" className="relative">
          <AnimatePresence initial={false}>
            {R.map((r) => {
              const upper = r.kind === "upper";
              return (
                <motion.div key={r.run_id} layout="position" role="listitem" tabIndex={0}
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.12 } }}
                  data-tip={`${r.name}\n${r.what}\nprediction error ${(+r.log_loss).toFixed(4)} (95% range ${(+r.log_loss_lo).toFixed(4)} to ${(+r.log_loss_hi).toFixed(4)})\npicked the winner in ${(100 * r.accuracy).toFixed(1)}% of ${fmt(r.n_games)} games${upper ? "\nupper bound: uses information only certain at puck drop" : ""}\ntechnical name: ${r.experiment}`}
                  className="grid grid-cols-[minmax(150px,1.3fr)_2fr_64px] items-center gap-x-4 gap-y-1 border-b border-line py-2.5 last:border-0 max-sm:grid-cols-[1fr_64px]">
                  <span className="min-w-0 text-[0.9375rem] leading-snug">
                    {r.name}{upper && <span className="ml-1.5 align-middle"><Chip tone="accent">upper bound</Chip></span>}
                  </span>
                  <span className="relative h-5 max-sm:col-span-2 max-sm:row-start-2">
                    <span className="absolute inset-x-0 top-1/2 h-px bg-line" />
                    <motion.span className={`absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full ${upper ? "bg-away/35" : "bg-home/30"}`}
                      initial={false} animate={{ left: x(r.log_loss_lo), width: `calc(${x(r.log_loss_hi)} - ${x(r.log_loss_lo)})` }} />
                    <motion.span className={`absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface ${upper ? "bg-away" : "bg-home"}`}
                      initial={false} animate={{ left: x(r.log_loss) }} />
                  </span>
                  <span className="num text-right text-[0.875rem] text-ink-2 max-sm:row-start-1 max-sm:col-start-2">{(+r.log_loss).toFixed(4)}</span>
                </motion.div>
              );
            })}
          </AnimatePresence>
          <div aria-hidden className="grid grid-cols-[minmax(150px,1.3fr)_2fr_64px] gap-x-4 pt-2 max-sm:grid-cols-[1fr]">
            <span className="t-cap max-sm:hidden">prediction error</span>
            <span className="relative h-4">
              {ticks.map((t) => <span key={t} className="num t-cap absolute -translate-x-1/2" style={{ left: x(t) }}>{t.toFixed(3)}</span>)}
            </span>
          </div>
        </div>
      </Card>
      <Note>Small differences matter here: 0.001 is a real gain in hockey. Overlapping ranges don't always mean a tie, because the project notes also compare models game by game.</Note>
      <details className="card group p-5 sm:p-6">
        <summary className="t-head cursor-pointer list-none">Table view <span className="text-muted group-open:hidden">(show)</span></summary>
        <div className="scroll-x mt-4">
          <table className="data">
            <thead><tr><th>Model</th><th className="!text-left">What it uses</th><th>Games</th><th>Prediction error</th><th>95% range</th><th>Picked the winner</th><th>Technical name</th></tr></thead>
            <tbody>{R.map((r) => (
              <tr key={r.run_id}>
                <td className="wrap">{r.name}{r.kind === "upper" ? " (upper bound)" : ""}</td><td className="wrap !text-left text-ink-2">{r.what}</td><td>{fmt(r.n_games)}</td>
                <td>{(+r.log_loss).toFixed(4)}</td><td>{(+r.log_loss_lo).toFixed(4)} to {(+r.log_loss_hi).toFixed(4)}</td>
                <td>{(100 * r.accuracy).toFixed(1)}%</td><td className="font-mono text-[0.75rem] text-muted">{r.experiment}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </details>
    </Page>
  );
}
