import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { fmt, seasonLabel, type Payload, type Run } from "../data";
import { Chip, Empty, gridKeys, Note, Panel, Screen, Segmented } from "../ui";

const PERIOD: Record<string, string> = { test: "Test seasons", dev: "Development seasons" };

export function Models({ D }: { D: Payload }) {
  const all = D.experiments?.rows ?? [];
  const periods = [...new Set(all.map((r) => r.period))].sort().reverse();   // test first
  const [period, setPeriod] = useState(periods.includes("test") ? "test" : periods[0] ?? "");
  const [more, setMore] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  if (!D.experiments) return <Screen index="04" kicker="Models" title="Models"><Empty title="The model scoreboard" need="graded model results." /></Screen>;

  const inPeriod = all.filter((r) => r.period === period);
  const R = inPeriod.filter((r) => more || r.kind !== "detail").sort((a, b) => a.log_loss - b.log_loss);
  const hidden = inPeriod.filter((r) => r.kind === "detail").length;
  const lo = Math.min(...R.map((r) => r.log_loss_lo)), hi = Math.max(...R.map((r) => r.log_loss_hi)), pad = (hi - lo) * 0.06;
  const a = lo - pad, b = hi + pad, x = (v: number) => `${(100 * (v - a)) / (b - a)}%`;
  const ticks = Array.from({ length: 5 }, (_, i) => a + ((b - a) * (i + 0.5)) / 5);
  const seasons = R[0] ? String(R[0].seasons).split("-").map(seasonLabel).join(" to ") : "";
  const sel = R.find((r) => r.run_id === picked) ?? R[0]!;

  return (
    <Screen index="04" kicker="Models" title="Model scoreboard"
      sub={<>Every model we tried, graded on its <b className="font-semibold text-ink">prediction error</b>: how far its stated chances were from what happened. Lower is better; a 50/50 guess scores 0.693.</>}
      aside={<div className="flex flex-wrap items-center gap-3">
        <Segmented id="period" label="Seasons" value={period} onChange={(v) => { setPeriod(v); setPicked(null); }} options={periods.map((p) => [p, PERIOD[p] ?? p])} />
        {hidden > 0 && <button type="button" onClick={() => setMore(!more)} className="press panel-2 px-3 py-1.5 text-[0.8125rem] font-semibold text-accent">
          {more ? "Hide" : "Show"} {hidden} tuning runs</button>}
      </div>}>
      <Panel className="col-span-12 xl:col-span-8" title={`${PERIOD[period] ?? period}, ${seasons}`}
        note={`${R[0] ? fmt(R[0].n_games) : 0} games. ${period === "test" ? "The real exam: every model was finalized before its test results were looked at." : "Used to build and tune the models, so these scores are a little optimistic."} Best first; the dot is the prediction error, the bar its 95% range. Select a row to inspect it.`}>
        <div role="listbox" aria-label="Models" className="relative" onKeyDown={gridKeys}>
          <AnimatePresence initial={false}>
            {R.map((r) => {
              const upper = r.kind === "upper", on = r.run_id === sel.run_id;
              return (
                <motion.div key={r.run_id} layout="position" role="option" aria-selected={on} aria-current={on} tabIndex={0} data-nav
                  onFocus={() => setPicked(r.run_id)} onPointerEnter={() => setPicked(r.run_id)} onClick={() => setPicked(r.run_id)}
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.12 } }}
                  className="relative grid cursor-pointer grid-cols-[minmax(150px,1.3fr)_2fr_64px] items-center gap-x-4 gap-y-1 rounded-[10px] px-2 py-2.5 outline-none max-sm:grid-cols-[1fr_64px]">
                  {on && <motion.span layoutId="model-sel" className="absolute inset-0 rounded-[10px] border border-[color-mix(in_srgb,var(--accent)_40%,transparent)]"
                    style={{ background: "linear-gradient(90deg, color-mix(in srgb, var(--accent) 16%, transparent), transparent)" }} />}
                  <span className="relative min-w-0 text-[0.9375rem] leading-snug">
                    {r.name}{upper && <span className="ml-1.5 align-middle"><Chip tone="accent">upper bound</Chip></span>}
                  </span>
                  <span className="relative h-5 max-sm:col-span-2 max-sm:row-start-2">
                    <span className="absolute inset-x-0 top-1/2 h-px bg-line" />
                    <motion.span className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full"
                      style={{ background: `color-mix(in srgb, ${upper ? "var(--away)" : "var(--home)"} 40%, transparent)` }}
                      initial={false} animate={{ left: x(r.log_loss_lo), width: `calc(${x(r.log_loss_hi)} - ${x(r.log_loss_lo)})` }} />
                    <motion.span className={`absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface-solid ${upper ? "bar-away" : "bar-home"}`}
                      style={{ boxShadow: `0 0 12px ${upper ? "var(--away)" : "var(--home)"}` }} initial={false} animate={{ left: x(r.log_loss) }} />
                  </span>
                  <span className="num relative text-right text-[0.875rem] text-ink-2 max-sm:col-start-2 max-sm:row-start-1">{(+r.log_loss).toFixed(4)}</span>
                </motion.div>
              );
            })}
          </AnimatePresence>
          <div aria-hidden className="grid grid-cols-[minmax(150px,1.3fr)_2fr_64px] gap-x-4 px-2 pt-2 max-sm:grid-cols-[1fr]">
            <span className="t-cap max-sm:hidden">prediction error</span>
            <span className="relative h-4">{ticks.map((t) => <span key={t} className="num t-cap absolute -translate-x-1/2" style={{ left: x(t) }}>{t.toFixed(3)}</span>)}</span>
          </div>
        </div>
      </Panel>
      <div className="col-span-12 flex flex-col gap-4 xl:sticky xl:top-16 xl:col-span-4 xl:self-start lg:gap-5">
        <Inspector r={sel} best={R[0]!} />
        <Note>Small differences matter here: 0.001 is a real gain in hockey. Overlapping ranges don't always mean a tie, because the project notes also compare models game by game.</Note>
      </div>
      <details className="panel group col-span-12 p-4 sm:p-5">
        <summary className="t-head cursor-pointer list-none">Table view <span className="text-muted normal-case group-open:hidden">(show)</span></summary>
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
    </Screen>
  );
}

/** The selected model, like a game's item inspector. */
function Inspector({ r, best }: { r: Run; best: Run }) {
  const gap = +r.log_loss - +best.log_loss;
  return (
    <Panel title="Inspect">
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.div key={r.run_id} initial={{ opacity: 0, y: 6, filter: "blur(4px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          exit={{ opacity: 0, transition: { duration: 0.1 } }} transition={{ duration: 0.22, ease: [0.23, 1, 0.32, 1] }}>
          <div className="text-[1.25rem] font-bold tracking-[-0.01em]">{r.name}</div>
          <p className="m-0 mt-1 text-[0.9375rem] text-ink-2">{r.what}</p>
          {r.kind === "upper" && <div className="mt-2"><Chip tone="accent">Upper bound: uses information only certain at puck drop</Chip></div>}
          <div className="mt-4 grid grid-cols-2 gap-2">
            {[["Prediction error", (+r.log_loss).toFixed(4)], ["Picked the winner", `${(100 * r.accuracy).toFixed(1)}%`],
              ["95% range", `${(+r.log_loss_lo).toFixed(3)}-${(+r.log_loss_hi).toFixed(3)}`], ["Behind the best", gap < 5e-5 ? "Best" : `+${gap.toFixed(4)}`]].map(([k, v]) => (
              <div key={k} className="panel-2 p-3"><div className="t-cap">{k}</div><div className="num mt-1 text-[1.125rem] font-bold">{v}</div></div>
            ))}
          </div>
          <div className="t-cap mt-3">{fmt(r.n_games)} games &middot; technical name <span className="font-mono">{r.experiment}</span></div>
        </motion.div>
      </AnimatePresence>
    </Panel>
  );
}
