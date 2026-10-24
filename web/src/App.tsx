import { AnimatePresence, motion, MotionConfig, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Payload } from "./data";
import { Games } from "./pages/Games";
import { Models } from "./pages/Models";
import { Overview } from "./pages/Overview";
import { PaperPage } from "./pages/Paper";
import { GameDetail, UpcomingPage } from "./pages/Upcoming";
import { Settings, usePrefs } from "./Settings";
import { SPRING } from "./ui";

const ICON: Record<string, ReactNode> = {
  overview: <path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" />,
  upcoming: <><rect x="4" y="5" width="16" height="15" rx="2.5" /><path d="M4 10h16M9 3v4M15 3v4" /></>,
  paper: <path d="M4 18l5-6 4 3 7-9M15 6h5v5" />,
  experiments: <path d="M5 20V10M12 20V4M19 20v-7" />,
  games: <><path d="M5 6h14M5 12h14M5 18h14" /></>,
};
export const AREAS = [
  { id: "overview", label: "Overview", short: "Overview" },
  { id: "upcoming", label: "Upcoming", short: "Upcoming" },
  { id: "paper", label: "Paper bets", short: "Bets" },
  { id: "experiments", label: "Models", short: "Models" },
  { id: "games", label: "Game log", short: "Games" },
] as const;
type AreaId = (typeof AREAS)[number]["id"];

function useRoute(): [AreaId, string | undefined] {
  const read = (): [AreaId, string | undefined] => {
    const [h, sub] = location.hash.replace(/^#\/?/, "").split("/");
    return [AREAS.some((a) => a.id === h) ? (h as AreaId) : "overview", sub];
  };
  const [r, setR] = useState(read);
  useEffect(() => { const on = () => setR(read()); addEventListener("hashchange", on); return () => removeEventListener("hashchange", on); }, []);
  return r;
}

const Icon = ({ id }: { id: string }) => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{ICON[id]}</svg>
);
const href = (id: string) => (id === "overview" ? "#/" : `#/${id}`);

export function App({ D }: { D: Payload }) {
  const [area, sub] = useRoute();
  const prefs = usePrefs();
  const [settings, setSettings] = useState(() => location.hash === "#/settings");
  const gear = useRef<HTMLButtonElement>(null);
  useTooltip();

  const key = `${area}/${sub ?? ""}`;
  useEffect(() => { scrollTo({ top: 0 }); }, [key]);
  useEffect(() => { document.title = area === "overview" ? "Swedish Suede" : `${AREAS.find((a) => a.id === area)!.label} - Swedish Suede`; }, [area]);

  const page = area === "upcoming" && sub ? <GameDetail D={D} id={sub} />
    : area === "upcoming" ? <UpcomingPage D={D} />
    : area === "paper" ? <PaperPage D={D} />
    : area === "experiments" ? <Models D={D} />
    : area === "games" ? <Games D={D} />
    : <Overview D={D} />;

  return (
    <MotionConfig reducedMotion={prefs.motion === "reduced" ? "always" : "user"} transition={SPRING}>
      <header className="glass sticky top-0 z-30 border-b border-line">
        <div className="mx-auto flex h-14 max-w-[1080px] items-center gap-4 px-4 sm:px-6">
          <a href="#/" className="flex items-center gap-2 text-[1.0625rem] font-semibold tracking-[-0.01em] text-ink no-underline">
            <span aria-hidden className="grid size-7 place-items-center rounded-[8px] bg-accent text-[var(--accent-ink)]">
              <svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="4.5" fill="none" stroke="currentColor" strokeWidth="2" /></svg>
            </span>
            Swedish Suede
          </a>
          <nav aria-label="Sections" className="ml-auto hidden md:block">
            <ul className="m-0 flex list-none gap-1 p-0">
              {AREAS.map((a) => (
                <li key={a.id}>
                  <a href={href(a.id)} aria-current={a.id === area ? "page" : undefined}
                    className={`press relative block rounded-full px-3.5 py-1.5 text-[0.875rem] font-medium no-underline ${a.id === area ? "text-ink" : "text-muted hover:text-ink"}`}>
                    {a.id === area && <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-full bg-surface-2" />}
                    <span className="relative">{a.label}</span>
                  </a>
                </li>
              ))}
            </ul>
          </nav>
          <button ref={gear} type="button" aria-label="Settings" aria-haspopup="dialog" onClick={() => setSettings(true)}
            className="press ml-auto grid size-9 place-items-center rounded-full text-ink-2 hover:bg-surface-2 md:ml-0">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
              <path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" />
            </svg>
          </button>
        </div>
      </header>

      <main>
        <AnimatePresence mode="wait" initial={false}>
          <PageFade key={key}>{page}</PageFade>
        </AnimatePresence>
      </main>

      <footer className="mx-auto hidden max-w-[1080px] justify-between gap-4 px-6 pb-10 text-[0.75rem] text-muted md:flex">
        <span>For analysis only. Not betting advice.</span>
        <span className="num">Built {D.built_at} &middot; rev {D.git_rev}</span>
      </footer>

      {/* phone: tab bar at the bottom, in thumb reach */}
      <nav aria-label="Sections" className="glass fixed inset-x-0 bottom-0 z-30 border-t border-line pb-[env(safe-area-inset-bottom)] md:hidden">
        <ul className="m-0 grid list-none grid-cols-5 p-0">
          {AREAS.map((a) => (
            <li key={a.id}>
              <a href={href(a.id)} aria-current={a.id === area ? "page" : undefined}
                className={`press flex flex-col items-center gap-0.5 pt-2 pb-1.5 text-[0.625rem] font-medium no-underline ${a.id === area ? "text-accent" : "text-muted"}`}>
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

/** Pages arrive with a short ease-out fade and leave faster than they came. */
function PageFade({ children }: { children: ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <motion.div initial={{ opacity: 0, y: reduce ? 0 : 8, filter: reduce ? "none" : "blur(4px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.28, ease: [0.23, 1, 0.32, 1] } }}
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
