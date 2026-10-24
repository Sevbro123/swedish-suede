import NumberFlow, { type Format } from "@number-flow/react";
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import type { KeyboardEvent, ReactNode } from "react";
import { teamColor } from "./teams";

export const SPRING = { type: "spring", bounce: 0, duration: 0.4 } as const;

/** One screen of the app: a menu-style header, then content laid out over the full width. */
export function Screen({ index, kicker, title, sub, aside, children, back }:
  { index: string; kicker: string; title: ReactNode; sub?: ReactNode; aside?: ReactNode; children: ReactNode; back?: ReactNode }) {
  return (
    <div className="w-full px-4 pt-5 pb-28 sm:px-6 lg:px-8 lg:pt-7 lg:pb-20">
      {back}
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
        <div className="min-w-0">
          <div className="t-kicker">{index} / {kicker}</div>
          <h1 className="t-display m-0 mt-2">{title}</h1>
          {sub && <div className="mt-2 max-w-[90ch] text-[0.9375rem] leading-relaxed text-ink-2">{sub}</div>}
        </div>
        {aside}
      </header>
      <div className="mt-6 grid grid-cols-12 gap-4 lg:gap-5">{children}</div>
    </div>
  );
}

/** Column spans on the 12-column screen grid: full width on phones, the given span from xl up. */
export const span = { full: "col-span-12", 8: "col-span-12 xl:col-span-8", 7: "col-span-12 xl:col-span-7", 6: "col-span-12 lg:col-span-6",
  5: "col-span-12 xl:col-span-5", 4: "col-span-12 md:col-span-6 xl:col-span-4", 3: "col-span-12 md:col-span-6 xl:col-span-3" } as const;

export function Panel({ title, note, children, className = "", right }: { title?: ReactNode; note?: ReactNode; children: ReactNode; className?: string; right?: ReactNode }) {
  return (
    <section className={`panel min-w-0 p-4 sm:p-5 ${className}`}>
      {(title || right) && (
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            {title && <h2 className="t-head m-0">{title}</h2>}
            {note && <p className="t-cap m-0 mt-1 text-[0.8125rem]">{note}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

/** A headline number. Numbers count to their value with NumberFlow; text values render as-is. */
export function Stat({ k, v, s, format, tone }: { k: string; v: number | string | null; s?: ReactNode; format?: Format; tone?: "accent" }) {
  return (
    <div className="panel col-span-6 overflow-hidden p-4 sm:p-5 xl:col-span-3">
      <div aria-hidden className="pointer-events-none absolute -top-10 -right-10 size-32 rounded-full opacity-60 blur-2xl" style={{ background: "rgb(var(--glow-a) / 0.18)" }} />
      <div className="t-head text-[0.6875rem]">{k}</div>
      <div className={`num mt-2 text-[2rem] leading-none font-semibold tracking-[-0.03em] ${tone === "accent" ? "text-accent" : ""}`}>
        {typeof v === "number" ? <NumberFlow value={v} format={format} /> : (v ?? "-")}
      </div>
      {s && <div className="mt-2 text-[0.8125rem] leading-snug text-ink-2">{s}</div>}
    </div>
  );
}

export function Chip({ children, tone, tip }: { children: ReactNode; tone?: "good" | "bad" | "accent"; tip?: string }) {
  const c = tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : tone === "accent" ? "text-accent" : "text-ink-2";
  return (
    <span data-tip={tip} className={`inline-flex items-center rounded-full border border-line bg-surface-2 px-2.5 py-0.5 text-[0.6875rem] font-semibold tracking-[0.04em] whitespace-nowrap uppercase ${c}`}>
      {children}
    </span>
  );
}

export const TeamDot = ({ ab, size = 10 }: { ab: string; size?: number }) => (
  <i aria-hidden className="inline-block shrink-0 rounded-full" style={{ width: size, height: size, background: teamColor(ab), boxShadow: "0 0 0 1.5px var(--line-strong), 0 0 10px " + teamColor(ab) + "66" }} />
);

/** Segmented control; the selection pill slides between options on a critically damped spring. */
export function Segmented<T extends string>({ value, options, onChange, id, label }:
  { value: T; options: [T, string][]; onChange: (v: T) => void; id: string; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-[11px] border border-line bg-surface-2 p-0.5 shadow-[inset_0_1px_2px_rgb(0_0_0/0.25)]">
      {options.map(([v, l]) => (
        <button key={v} type="button" role="radio" aria-checked={v === value} onClick={() => onChange(v)}
          className={`press relative rounded-[9px] px-3.5 py-1.5 text-[0.8125rem] font-semibold ${v === value ? "text-ink" : "text-muted hover:text-ink-2"}`}>
          {v === value && <motion.span layoutId={`seg-${id}`} transition={SPRING} className="panel-2 absolute inset-0 rounded-[9px] !bg-surface-solid" />}
          <span className="relative">{l}</span>
        </button>
      ))}
    </div>
  );
}

/** Away vs home win chance on one track. The away share grows from the middle so the bar telegraphs who leads. */
export function ProbBar({ away, home, pHome, big }: { away: string; home: string; pHome: number; big?: boolean }) {
  const h = Math.round(100 * pHome), a = 100 - h, reduce = useReducedMotion();
  return (
    <div role="img" aria-label={`${away} ${a} percent, ${home} ${h} percent`}>
      <div className={`num flex justify-between font-bold tracking-[-0.02em] ${big ? "text-[1.75rem]" : "text-[1.0625rem]"}`}>
        <span className="text-away">{a}%</span><span className="text-home">{h}%</span>
      </div>
      <div className={`relative mt-1.5 overflow-hidden rounded-full bar-home shadow-[inset_0_1px_2px_rgb(0_0_0/0.3)] ${big ? "h-4" : "h-2.5"}`}>
        <motion.div className="bar-away absolute inset-y-0 left-0 w-full origin-left" initial={reduce ? false : { scaleX: 0.5 }}
          animate={{ scaleX: a / 100 }} transition={{ type: "spring", bounce: 0, duration: 0.7 }} />
        <span className="absolute inset-y-0 w-[3px] bg-surface-solid" style={{ left: `calc(${a}% - 1.5px)` }} />
      </div>
    </div>
  );
}

/** A selectable tile that tilts toward the pointer on a spring (decorative; off for touch and reduced motion). */
export function Tilt({ children, className = "" }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion(), x = useMotionValue(0), y = useMotionValue(0);
  const rx = useSpring(useTransform(y, [-0.5, 0.5], [4, -4]), { stiffness: 220, damping: 22 });
  const ry = useSpring(useTransform(x, [-0.5, 0.5], [-5, 5]), { stiffness: 220, damping: 22 });
  return (
    <motion.div className={className} style={reduce ? undefined : { rotateX: rx, rotateY: ry, transformPerspective: 900 }}
      onPointerMove={(e) => { if (e.pointerType !== "mouse") return; const r = e.currentTarget.getBoundingClientRect(); x.set((e.clientX - r.left) / r.width - 0.5); y.set((e.clientY - r.top) / r.height - 0.5); }}
      onPointerLeave={() => { x.set(0); y.set(0); }}>
      {children}
    </motion.div>
  );
}

/** Arrow keys move focus between the [data-nav] items of a grid, to the nearest one in that direction (like a game's level select). */
export function gridKeys(e: KeyboardEvent<HTMLElement>) {
  const d = ({ ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] } as Record<string, [number, number]>)[e.key];
  const cur = (e.target as HTMLElement).closest<HTMLElement>("[data-nav]");
  if (!d || !cur) return;
  const c = cur.getBoundingClientRect(), cx = c.left + c.width / 2, cy = c.top + c.height / 2;
  let best: HTMLElement | null = null, bestScore = Infinity;
  e.currentTarget.querySelectorAll<HTMLElement>("[data-nav]").forEach((el) => {
    if (el === cur) return;
    const r = el.getBoundingClientRect(), dx = r.left + r.width / 2 - cx, dy = r.top + r.height / 2 - cy;
    const along = dx * d[0] + dy * d[1], across = Math.abs(dx * d[1]) + Math.abs(dy * d[0]);
    if (along <= 1) return;
    const score = along + across * 2;
    if (score < bestScore) { bestScore = score; best = el; }
  });
  if (best) { e.preventDefault(); (best as HTMLElement).focus(); (best as HTMLElement).scrollIntoView({ block: "nearest" }); }
}

export function Empty({ title, need }: { title: string; need: string }) {
  return (
    <div className="panel col-span-12 flex flex-col items-start gap-2 p-8">
      <div className="t-kicker !text-muted">Locked</div>
      <div className="text-[1.25rem] font-semibold">{title} isn't ready yet</div>
      <p className="m-0 max-w-[70ch] text-ink-2">It opens once the project has {need} We don't show made-up numbers, so this stays empty until the real results exist.</p>
    </div>
  );
}

export const Note = ({ children, className = "" }: { children: ReactNode; className?: string }) => <p className={`t-cap m-0 text-[0.8125rem] ${className}`}>{children}</p>;

export const Bullets = ({ items }: { items: ReactNode[] }) => (
  <ul className="m-0 flex list-none flex-col gap-2.5 p-0 text-[0.9375rem] text-ink-2">
    {items.map((x, i) => <li key={i} className="relative pl-4 before:absolute before:top-[0.55em] before:left-0 before:size-1.5 before:rounded-full before:bg-accent before:shadow-[0_0_8px_var(--accent)] before:content-['']">{x}</li>)}
  </ul>
);

export const Gloss = ({ items, stacked }: { items: [string, ReactNode][]; stacked?: boolean }) => (
  <dl className={`m-0 grid gap-x-6 text-[0.9375rem] ${stacked ? "gap-y-1" : "gap-y-3 sm:grid-cols-[max-content_1fr]"}`}>
    {items.map(([k, v]) => [<dt key={k + "t"} className={`font-semibold ${stacked ? "t-head mt-2 text-[0.6875rem] first:mt-0" : ""}`}>{k}</dt>, <dd key={k + "d"} className="m-0 text-ink-2">{v}</dd>])}
  </dl>
);

export const Legend = ({ items }: { items: [string, string][] }) => (
  <div className="flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem] text-ink-2">
    {items.map(([c, l]) => <span key={l} className="flex items-center gap-1.5 whitespace-nowrap"><i className="block h-[3px] w-4 rounded-full" style={{ background: c }} />{l}</span>)}
  </div>
);

export const BackLink = ({ href, children }: { href: string; children: ReactNode }) => (
  <a href={href} className="press mb-4 inline-flex items-center gap-2 text-[0.875rem] font-semibold text-accent no-underline">
    <kbd>Esc</kbd>{children}
  </a>
);
