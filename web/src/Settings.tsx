import { AnimatePresence, motion, type PanInfo } from "motion/react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { contrast, TEAMS, teamAccent } from "./teams";
import { Segmented } from "./ui";

type Theme = "system" | "light" | "dark";
type MotionPref = "full" | "reduced";
const store = {
  get: (k: string) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* unavailable */ } },
};
const dark = matchMedia("(prefers-color-scheme: dark)");

export function usePrefs() {
  const [theme, setTheme] = useState<Theme>(() => (["light", "dark"].includes(store.get("suede.theme") ?? "") ? store.get("suede.theme") as Theme : "system"));
  const [team, setTeam] = useState(() => (TEAMS.some((t) => t[0] === store.get("suede.team")) ? store.get("suede.team")! : ""));
  const [motionPref, setMotion] = useState<MotionPref>(() => (store.get("suede.fx") === "off" ? "reduced" : "full"));
  const [sys, setSys] = useState(dark.matches);
  useEffect(() => { const on = () => setSys(dark.matches); dark.addEventListener("change", on); return () => dark.removeEventListener("change", on); }, []);
  const mode = theme === "system" ? (sys ? "dark" : "light") : theme;

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = mode;
    const t = TEAMS.find((x) => x[0] === team);
    if (t) {
      const a = teamAccent(t[2], mode), rgb = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
      root.style.setProperty("--accent", a);
      root.style.setProperty("--accent-ink", contrast(rgb, [255, 255, 255]) >= 4.5 ? "#ffffff" : "#000000");
    } else { root.style.removeProperty("--accent"); root.style.removeProperty("--accent-ink"); }
  }, [mode, team]);

  return {
    theme, team, motion: motionPref, mode,
    setTheme: (v: Theme) => {
      // ease the brightness jump between light and dark
      document.documentElement.classList.add("theme-fade"); setTimeout(() => document.documentElement.classList.remove("theme-fade"), 320);
      setTheme(v); store.set("suede.theme", v === "system" ? "" : v);
    },
    setTeam: (v: string) => { setTeam(v); store.set("suede.team", v); },
    setMotion: (v: MotionPref) => { setMotion(v); store.set("suede.fx", v === "reduced" ? "off" : "on"); },
  };
}
type Prefs = ReturnType<typeof usePrefs>;

const phone = matchMedia("(max-width: 767px)");

/** A bottom sheet on phones (drag or flick it down to close), a popover from the settings button elsewhere. */
export function Settings({ open, onClose, prefs }: { open: boolean; onClose: () => void; prefs: Prefs }) {
  const panel = useRef<HTMLDivElement>(null);
  const [isPhone, setPhone] = useState(phone.matches);
  useEffect(() => { const on = () => setPhone(phone.matches); phone.addEventListener("change", on); return () => phone.removeEventListener("change", on); }, []);
  useEffect(() => {
    if (!open) return;
    panel.current?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", key); return () => removeEventListener("keydown", key);
  }, [open, onClose]);

  const dragEnd = (_: unknown, info: PanInfo) => { if (info.offset.y > 120 || info.velocity.y > 500) onClose(); };
  const sheet = { initial: { y: "100%" }, animate: { y: 0 }, exit: { y: "100%" }, transition: { type: "spring", bounce: 0, duration: 0.35 } } as const;
  const pop = {
    initial: { opacity: 0, scale: 0.96, filter: "blur(6px)" }, animate: { opacity: 1, scale: 1, filter: "blur(0px)" },
    exit: { opacity: 0, scale: 0.98, filter: "blur(4px)", transition: { duration: 0.15 } }, transition: { type: "spring", bounce: 0, duration: 0.3 },
  } as const;

  return (
    <AnimatePresence>
      {open && [
        <motion.div key="scrim" className="fixed inset-0 z-40" style={{ background: isPhone ? "var(--scrim)" : "transparent" }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} onClick={onClose} />,
        <motion.div key="panel" ref={panel} role="dialog" aria-modal="true" aria-label="Settings" tabIndex={-1}
          className={`glass fixed z-50 overflow-y-auto outline-none ${isPhone
            ? "inset-x-0 bottom-0 max-h-[85vh] rounded-t-[22px] px-5 pt-2 pb-[calc(24px+env(safe-area-inset-bottom))]"
            : "top-[60px] right-[max(16px,calc((100vw-1080px)/2+16px))] max-h-[calc(100vh-80px)] w-[380px] origin-top-right rounded-[18px] p-5"}`}
          style={{ boxShadow: "var(--shadow-lg)" }}
          {...(isPhone ? { ...sheet, drag: "y" as const, dragConstraints: { top: 0, bottom: 0 }, dragElastic: { top: 0.05, bottom: 0.9 }, onDragEnd: dragEnd } : pop)}>
          {isPhone && <div aria-hidden className="mx-auto mb-3 h-[5px] w-9 rounded-full bg-[var(--line-strong)]" />}
          <div className="flex items-center justify-between">
            <h2 className="t-head m-0">Settings</h2>
            <button type="button" onClick={onClose} className="press rounded-full px-3 py-1 text-[0.9375rem] font-medium text-accent hover:bg-surface-2">Done</button>
          </div>
          <Row label="Appearance">
            <Segmented id="theme" label="Appearance" value={prefs.theme} onChange={prefs.setTheme} options={[["system", "Auto"], ["light", "Light"], ["dark", "Dark"]]} />
          </Row>
          <Row label="Motion" note="Reduced swaps movement for simple fades. Your device setting is respected either way.">
            <Segmented id="motion" label="Motion" value={prefs.motion} onChange={prefs.setMotion} options={[["full", "Full"], ["reduced", "Reduced"]]} />
          </Row>
          <div className="border-t border-line pt-4">
            <div className="text-[0.9375rem] font-medium">Team color</div>
            <p className="t-cap m-0 mt-0.5 mb-3">Tints buttons and links. Charts keep their own colors so they stay easy to read.</p>
            <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-5">
              {[["", "Default", ["#0071e3", "#2997ff"]] as [string, string, string[]], ...TEAMS].map(([ab, name, cols]) => (
                <button key={ab || "none"} type="button" aria-pressed={prefs.team === ab} aria-label={name} data-tip={name} onClick={() => prefs.setTeam(ab)}
                  className={`press flex flex-col items-center gap-1 rounded-[10px] py-2 text-[0.6875rem] font-medium ${prefs.team === ab ? "bg-surface-2 text-ink ring-2 ring-accent" : "text-ink-2 hover:bg-surface-2"}`}>
                  <span aria-hidden className="flex">
                    {cols.slice(0, 2).map((c, i) => <i key={i} className={`block size-4 rounded-full ${i ? "-ml-1.5" : ""}`} style={{ background: c, boxShadow: "0 0 0 1.5px var(--surface)" }} />)}
                  </span>
                  {ab || "Default"}
                </button>
              ))}
            </div>
            <p className="t-cap m-0 mt-3">Colors are decoration only. This project isn't affiliated with the NHL or any team.</p>
          </div>
        </motion.div>,
      ]}
    </AnimatePresence>
  );
}

const Row = ({ label, note, children }: { label: string; note?: string; children: React.ReactNode }) => (
  <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line py-4 first-of-type:mt-3">
    <div className="min-w-0">
      <div className="text-[0.9375rem] font-medium">{label}</div>
      {note && <p className="t-cap m-0 mt-0.5 max-w-[24ch]">{note}</p>}
    </div>
    {children}
  </div>
);
