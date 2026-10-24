import { AnimatePresence, motion, MotionConfig, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { pct, type Payload } from "./data";
import { Games } from "./pages/Games";
import { Models } from "./pages/Models";
import { Overview } from "./pages/Overview";
import { PaperPage } from "./pages/Paper";
import { GameDetail, UpcomingPage } from "./pages/Upcoming";
import { Settings, usePrefs } from "./Settings";
import { gridKeys, SPRING } from "./ui";

const ICON: Record<string, ReactNode> = {
  overview: <path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" />,
  upcoming: <><rect x="4" y="5" width="16" height="15" rx="2.5" /><path d="M4 10h16M9 3v4M15 3v4" /></>,
  paper: <path d="M4 18l5-6 4 3 7-9M15 6h5v5" />,
  experiments: <path d="M5 20V10M12 20V4M19 20v-7" />,
  games: <path d="M5 6h14M5 12h14M5 18h14" />,
};
export const AREAS = [
  { id: "overview", label: "Overview", short: "Overview", desc: "How well it works" },
  { id: "upcoming", label: "Upcoming", short: "Upcoming", desc: "Next games and why" },
  { id: "paper", label: "Paper bets", short: "Bets", desc: "Pretend bets vs the odds" },
  { id: "experiments", label: "Models", short: "Models", desc: "Every model, graded" },
  { id: "games", label: "Game log", short: "Games", desc: "Every graded game" },
] as const;
type AreaId = (typeof AREAS)[number]["id"];
const href = (id: string) => (id === "overview" ? "#/" : `#/${id}`);

function useRoute(): [AreaId, string | undefined] {
  const read = (): [AreaId, string | undefined] => {
    const [h, sub] = location.hash.replace(/^#\/?/, "").split("/");
    return [AREAS.some((a) => a.id === h) ? (h as AreaId) : "overview", sub];
  };
  const [r, setR] = useState(read);
  useEffect(() => { const on = () => setR(read()); addEventListener("hashchange", on); return () => removeEventListener("hashchange", on); }, []);
  return r;
}

const Icon = ({ id, size = 22 }: { id: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{ICON[id]}</svg>
);
const Logo = () => (
  <span aria-hidden className="bar-accent grid size-9 place-items-center rounded-[11px] text-[var(--accent-ink)] shadow-[0_6px_20px_-4px_var(--accent),inset_0_1px_0_rgb(255_255_255/0.35)]">
    <svg width="18" height="18" viewBox="0 0 16 16"><circle cx="8" cy="8" r="4.5" fill="none" stroke="currentColor" strokeWidth="2" /></svg>
  </span>
);

export function App({ D }: { D: Payload }) {
  const [area, sub] = useRoute();
  const prefs = usePrefs();
  const [settings, setSettings] = useState(() => location.hash === "#/settings");
  const gear = useRef<HTMLButtonElement>(null);
  useTooltip();

  const key = `${area}/${sub ?? ""}`;
  useEffect(() => { scrollTo({ top: 0 }); }, [key]);
  useEffect(() => { document.title = area === "overview" ? "Swedish Suede" : `${AREAS.find((a) => a.id === area)!.label} - Swedish Suede`; }, [area]);

  // game-menu controls: Q / E switch section, 1-5 jump, Esc backs out, comma opens settings
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || settings || /INPUT|SELECT|TEXTAREA/.test((e.target as HTMLElement).tagName)) return;
      const i = AREAS.findIndex((a) => a.id === area), k = e.key.toLowerCase();
      if (k === "q" || k === "e") location.hash = href(AREAS[(i + (k === "e" ? 1 : AREAS.length - 1)) % AREAS.length]!.id);
      else if (/^[1-5]$/.test(k)) location.hash = href(AREAS[+k - 1]!.id);
      else if (k === ",") { e.preventDefault(); setSettings(true); }
      else if (k === "escape" && sub) location.hash = href(area);
    };
    addEventListener("keydown", on); return () => removeEventListener("keydown", on);
  }, [area, sub, settings]);

  const page = area === "upcoming" && sub ? <GameDetail D={D} id={sub} />
    : area === "upcoming" ? <UpcomingPage D={D} />
    : area === "paper" ? <PaperPage D={D} />
    : area === "experiments" ? <Models D={D} />
    : area === "games" ? <Games D={D} />
    : <Overview D={D} />;
  const ready: Record<AreaId, boolean> = { overview: true, upcoming: !!D.live?.upcoming.length, paper: !!D.paper, experiments: !!D.experiments, games: !!D.predictions };
  const L = D.live, made = L?.updated_at ? (Date.now() - +new Date(L.updated_at)) / 6e4 : null;
  const ago = made == null ? "-" : made < 60 ? `${Math.max(1, Math.round(made))} min ago` : made < 2880 ? `${Math.round(made / 60)} h ago` : `${Math.round(made / 1440)} days ago`;

  return (
    <MotionConfig reducedMotion={prefs.motion === "reduced" ? "always" : "user"} transition={SPRING}>
      <div className="lg:grid lg:grid-cols-[272px_minmax(0,1fr)]">
        {/* ---------- side menu (desktop) ---------- */}
        <aside className="glass sticky top-0 hidden h-dvh flex-col border-r border-line lg:flex">
          <a href="#/" className="flex items-center gap-3 px-5 pt-6 pb-5 text-ink no-underline">
            <Logo />
            <span><span className="block text-[0.9375rem] font-bold tracking-[0.12em] uppercase">Swedish Suede</span>
              <span className="t-cap block">NHL win model</span></span>
          </a>
          <div className="t-kicker px-5 pb-2 !text-muted">Main menu</div>
          <nav aria-label="Sections" onKeyDown={gridKeys}>
            <ul className="m-0 flex list-none flex-col gap-1 px-3 p-0">
              {AREAS.map((a, i) => {
                const on = a.id === area;
                return (
                  <li key={a.id}>
                    <a href={href(a.id)} data-nav aria-current={on ? "page" : undefined}
                      className={`press group relative flex items-center gap-3 rounded-[12px] px-3 py-2.5 no-underline ${on ? "text-ink" : "text-muted hover:text-ink-2"}`}>
                      {on && <motion.span layoutId="menu-sel" className="absolute inset-0 rounded-[12px] border border-[color-mix(in_srgb,var(--accent)_45%,transparent)] shadow-[0_10px_30px_-12px_var(--accent),inset_0_1px_0_var(--hi)]"
                        style={{ background: "linear-gradient(90deg, color-mix(in srgb, var(--accent) 22%, transparent), color-mix(in srgb, var(--accent) 6%, transparent))" }} />}
                      {on && <motion.span layoutId="menu-bar" className="absolute top-2 bottom-2 -left-3 w-[3px] rounded-r-full bg-accent shadow-[0_0_12px_var(--accent)]" />}
                      <span className={`num relative w-6 font-mono text-[0.75rem] font-semibold ${on ? "text-accent" : ""}`}>{String(i + 1).padStart(2, "0")}</span>
                      <span className="relative min-w-0 flex-1">
                        <span className="block text-[0.875rem] font-bold tracking-[0.1em] uppercase">{a.label}</span>
                        <span className="t-cap block truncate">{ready[a.id] ? a.desc : "Locked: no data yet"}</span>
                      </span>
                      <span className={`relative transition-transform duration-200 ${on ? "translate-x-0 text-accent" : "-translate-x-1 opacity-0 group-hover:translate-x-0 group-hover:opacity-60"}`} aria-hidden>
                        <svg width="8" height="12" viewBox="0 0 8 12"><path d="M1.5 1l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      </span>
                    </a>
                  </li>
                );
              })}
            </ul>
          </nav>

          <div className="mt-auto flex flex-col gap-3 p-4">
            {L && (
              <div className="panel-2 p-3 text-[0.8125rem]">
                <div className="flex items-center gap-2 font-semibold"><i className="live-dot block size-2 rounded-full bg-good shadow-[0_0_8px_var(--good)]" />Live <span className="ml-auto font-normal text-muted">{ago}</span></div>
                {L.season_record && <div className="mt-2 flex justify-between text-ink-2"><span>{L.label} picked right</span><span className="num font-semibold text-ink">{pct(L.season_record.accuracy)}</span></div>}
                <div className="mt-1 flex justify-between text-ink-2"><span>Games on deck</span><span className="num font-semibold text-ink">{L.upcoming.length}</span></div>
              </div>
            )}
            <button ref={gear} type="button" onClick={() => setSettings(true)} aria-haspopup="dialog"
              className="press panel-2 flex items-center gap-2 px-3 py-2.5 text-[0.8125rem] font-semibold tracking-[0.08em] text-ink-2 uppercase hover:text-ink">
              <Sliders />Settings<kbd className="ml-auto">,</kbd>
            </button>
            <div className="t-cap num px-1">Built {D.built_at} &middot; rev {D.git_rev}<br />Analysis only. Not betting advice.</div>
          </div>
        </aside>

        <div className="min-w-0">
          {/* ---------- top bar: brand on phones, controls on desktop ---------- */}
          <header className="glass sticky top-0 z-30 border-b border-line">
            <div className="flex h-12 items-center gap-4 px-4 sm:px-6 lg:px-8">
              <a href="#/" className="flex items-center gap-2.5 text-[0.875rem] font-bold tracking-[0.1em] text-ink uppercase no-underline lg:hidden"><Logo />Swedish Suede</a>
              <div className="hidden items-center gap-5 text-[0.75rem] text-muted lg:flex">
                <span className="flex items-center gap-1.5"><kbd>Q</kbd><kbd>E</kbd>Switch</span>
                <span className="flex items-center gap-1.5"><kbd>1</kbd>-<kbd>5</kbd>Jump</span>
                <span className="flex items-center gap-1.5"><kbd>&larr;</kbd><kbd>&rarr;</kbd>Move</span>
                <span className="flex items-center gap-1.5"><kbd>Enter</kbd>Open</span>
                <span className="flex items-center gap-1.5"><kbd>Esc</kbd>Back</span>
              </div>
              <button type="button" aria-label="Settings" aria-haspopup="dialog" onClick={() => setSettings(true)}
                className="press ml-auto grid size-9 place-items-center rounded-full text-ink-2 hover:bg-surface-2 lg:hidden"><Sliders /></button>
            </div>
          </header>
          <main>
            <AnimatePresence mode="wait" initial={false}>
              <PageFade key={key}>{page}</PageFade>
            </AnimatePresence>
          </main>
        </div>
      </div>

      {/* phone and tablet: tab bar at the bottom, in thumb reach */}
      <nav aria-label="Sections" className="glass fixed inset-x-0 bottom-0 z-30 border-t border-line pb-[env(safe-area-inset-bottom)] lg:hidden">
        <ul className="m-0 grid list-none grid-cols-5 p-0">
          {AREAS.map((a) => (
            <li key={a.id}>
              <a href={href(a.id)} aria-current={a.id === area ? "page" : undefined}
                className={`press flex flex-col items-center gap-0.5 pt-2 pb-1.5 text-[0.625rem] font-semibold tracking-[0.04em] uppercase no-underline ${a.id === area ? "text-accent" : "text-muted"}`}>
                <Icon id={a.id} />{a.short}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <Settings open={settings} onClose={() => { setSettings(false); gear.current?.focus(); if (location.hash === "#/settings") location.hash = "#/"; }} prefs={prefs} />
      <div id="tip" role="tooltip" className="glass" />
    </MotionConfig>
  );
}

const Sliders = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
    <path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" />
  </svg>
);

/** Screens arrive with a short ease-out fade and leave faster than they came. */
function PageFade({ children }: { children: ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <motion.div initial={{ opacity: 0, y: reduce ? 0 : 10, filter: reduce ? "none" : "blur(6px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.3, ease: [0.23, 1, 0.32, 1] } }}
      exit={{ opacity: 0, transition: { duration: 0.12, ease: "easeOut" } }}>
      {children}
    </motion.div>
  );
}

/** Tooltips for anything with data-tip: the first waits a beat, later ones show instantly. */
function useTooltip() {
  useEffect(() => {
    const tip = document.getElementById("tip")!;
    let cur: Element | null = null, timer = 0, lastHide = 0;
    const place = (x: number, y: number) => {
      const r = tip.getBoundingClientRect(), left = Math.max(8, Math.min(x + 12, innerWidth - r.width - 8));
      const top = y + 16 + r.height > innerHeight - 8 ? y - r.height - 12 : y + 16;
      tip.style.left = `${left}px`; tip.style.top = `${Math.max(8, top)}px`;
    };
    const show = (el: Element, x: number, y: number) => {
      tip.textContent = el.getAttribute("data-tip"); place(x, y);
      const instant = performance.now() - lastHide < 500;
      tip.classList.toggle("instant", instant);
      clearTimeout(timer);
      if (instant) tip.classList.add("on"); else timer = window.setTimeout(() => tip.classList.add("on"), 350);
    };
    const hide = () => { if (cur) lastHide = performance.now(); cur = null; clearTimeout(timer); tip.classList.remove("on"); };
    const move = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      const el = (e.target as Element).closest?.("[data-tip]");
      if (!el) return hide();
      if (el !== cur) { cur = el; show(el, e.clientX, e.clientY); } else place(e.clientX, e.clientY);
    };
    const focus = (e: FocusEvent) => {
      const el = (e.target as Element).closest?.("[data-tip]");
      if (el && (e.target as HTMLElement).matches(":focus-visible")) { cur = el; const r = el.getBoundingClientRect(); show(el, r.left, r.bottom - 8); }
    };
    addEventListener("pointermove", move); addEventListener("focusin", focus); addEventListener("focusout", hide); addEventListener("scroll", hide, { passive: true });
    return () => { removeEventListener("pointermove", move); removeEventListener("focusin", focus); removeEventListener("focusout", hide); removeEventListener("scroll", hide); };
  }, []);
}
