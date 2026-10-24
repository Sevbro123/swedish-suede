import NumberFlow, { type Format } from "@number-flow/react";
import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { teamColor } from "./teams";

export const SPRING = { type: "spring", bounce: 0, duration: 0.4 } as const;

export function Page({ title, sub, children, back }: { title: ReactNode; sub?: ReactNode; children: ReactNode; back?: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-[1080px] px-4 pt-6 pb-28 sm:px-6 sm:pt-10 md:pb-16">
      {back}
      <h1 className="t-display m-0">{title}</h1>
      {sub && <div className="mt-3 max-w-[68ch] text-[1.0625rem] leading-relaxed text-ink-2">{sub}</div>}
      <div className="mt-8 flex flex-col gap-6">{children}</div>
    </div>
  );
}

export function Card({ title, note, children, className = "", tight }: { title?: ReactNode; note?: ReactNode; children: ReactNode; className?: string; tight?: boolean }) {
  return (
    <section className={`card min-w-0 ${tight ? "p-4" : "p-5 sm:p-6"} ${className}`}>
      {title && <h2 className="t-head m-0 mb-1">{title}</h2>}
      {note && <p className="t-cap m-0 mb-4 text-[0.8125rem]">{note}</p>}
      {!note && title && <div className="mb-3" />}
      {children}
    </section>
  );
}

/** A headline number. Numbers count to their value with NumberFlow; text values render as-is. */
export function Stat({ k, v, s, format, tip }: { k: string; v: number | string | null; s?: ReactNode; format?: Format; tip?: string }) {
  return (
    <div className="card p-4 sm:p-5" data-tip={tip} tabIndex={tip ? 0 : undefined}>
      <div className="t-cap text-[0.8125rem]">{k}</div>
      <div className="num mt-1 text-[1.875rem] font-semibold leading-tight tracking-[-0.02em]">
        {typeof v === "number" ? <NumberFlow value={v} format={format} /> : (v ?? "-")}
      </div>
      {s && <div className="mt-1 text-[0.8125rem] leading-snug text-ink-2">{s}</div>}
    </div>
  );
}

export const Stats = ({ children }: { children: ReactNode }) => (
  <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">{children}</div>
);

export function Chip({ children, tone, tip }: { children: ReactNode; tone?: "good" | "bad" | "accent"; tip?: string }) {
  const c = tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : tone === "accent" ? "text-accent" : "text-ink-2";
  return (
    <span data-tip={tip} className={`inline-flex items-center rounded-full bg-surface-2 px-2.5 py-0.5 text-[0.75rem] font-medium whitespace-nowrap ${c}`}>
      {children}
    </span>
  );
}

export const TeamDot = ({ ab, size = 10 }: { ab: string; size?: number }) => (
  <i aria-hidden className="inline-block shrink-0 rounded-full" style={{ width: size, height: size, background: teamColor(ab), boxShadow: "0 0 0 1px var(--line-strong)" }} />
);

/** Segmented control; the selection pill slides between options on a critically damped spring. */
export function Segmented<T extends string>({ value, options, onChange, id, label }:
  { value: T; options: [T, string][]; onChange: (v: T) => void; id: string; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-[10px] bg-surface-2 p-0.5">
      {options.map(([v, l]) => (
        <button key={v} type="button" role="radio" aria-checked={v === value} onClick={() => onChange(v)}
          className={`press relative rounded-[8px] px-3.5 py-1.5 text-[0.8125rem] font-medium ${v === value ? "text-ink" : "text-muted"}`}>
          {v === value && <motion.span layoutId={`seg-${id}`} transition={SPRING} className="absolute inset-0 rounded-[8px] bg-surface shadow-[0_1px_3px_rgb(0_0_0/0.12)]" />}
          <span className="relative">{l}</span>
        </button>
      ))}
    </div>
  );
}

/** Away vs home win chance on one track. The away share grows from the center so the bar telegraphs who leads. */
export function ProbBar({ away, home, pHome, big }: { away: string; home: string; pHome: number; big?: boolean }) {
  const h = Math.round(100 * pHome), a = 100 - h, reduce = useReducedMotion();
  return (
    <div role="img" aria-label={`${away} ${a} percent, ${home} ${h} percent`}>
      <div className={`num flex justify-between font-semibold ${big ? "text-[1.25rem]" : "text-[0.9375rem]"}`}>
        <span className="text-away">{a}%</span><span className="text-home">{h}%</span>
      </div>
      <div className={`relative mt-1.5 overflow-hidden rounded-full bg-home ${big ? "h-3" : "h-2"}`}>
        <motion.div className="absolute inset-y-0 left-0 w-full origin-left bg-away" initial={reduce ? false : { scaleX: 0.5 }}
          animate={{ scaleX: a / 100 }} transition={{ type: "spring", bounce: 0, duration: 0.7 }} />
        <span className="absolute inset-y-0 w-[2px] bg-surface" style={{ left: `calc(${a}% - 1px)` }} />
      </div>
    </div>
  );
}

export function Empty({ title, need }: { title: string; need: string }) {
  return (
    <div className="card flex flex-col items-start gap-2 p-8">
      <div className="t-head">{title} isn't ready yet</div>
      <p className="m-0 max-w-[60ch] text-ink-2">It opens once the project has {need} We don't show made-up numbers, so this stays empty until the real results exist.</p>
    </div>
  );
}

export const Note = ({ children }: { children: ReactNode }) => <p className="t-cap m-0 text-[0.8125rem]">{children}</p>;

export const Bullets = ({ items }: { items: ReactNode[] }) => (
  <ul className="m-0 flex list-none flex-col gap-2.5 p-0 text-[0.9375rem] text-ink-2">
    {items.map((x, i) => <li key={i} className="relative pl-4 before:absolute before:top-[0.6em] before:left-0 before:size-1.5 before:rounded-full before:bg-line before:content-['']">{x}</li>)}
  </ul>
);

export const Gloss = ({ items }: { items: [string, ReactNode][] }) => (
  <dl className="m-0 grid gap-x-6 gap-y-3 text-[0.9375rem] sm:grid-cols-[max-content_1fr]">
    {items.map(([k, v]) => [<dt key={k + "t"} className="font-medium">{k}</dt>, <dd key={k + "d"} className="m-0 text-ink-2">{v}</dd>])}
  </dl>
);

export const BackLink = ({ href, children }: { href: string; children: ReactNode }) => (
  <a href={href} className="press mb-4 inline-flex items-center gap-1 text-[1.0625rem] text-accent no-underline">
    <svg width="10" height="16" viewBox="0 0 10 16" aria-hidden><path d="M8 2L2 8l6 6" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
    {children}
  </a>
);
