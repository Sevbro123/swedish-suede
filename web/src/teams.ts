// Team colors: [abbrev, name, [primary, secondary, extra]]. Used for the accent color and team dots only.
export const TEAMS: [string, string, string[]][] = [
  ["ANA", "Anaheim Ducks", ["#F47A38", "#B9975B", "#000000"]], ["BOS", "Boston Bruins", ["#FFB81C", "#000000"]],
  ["BUF", "Buffalo Sabres", ["#003087", "#FFB81C"]], ["CGY", "Calgary Flames", ["#C8102E", "#F1BE48"]],
  ["CAR", "Carolina Hurricanes", ["#CE1126", "#A4A9AD", "#000000"]], ["CHI", "Chicago Blackhawks", ["#CF0A2C", "#000000", "#FFD100"]],
  ["COL", "Colorado Avalanche", ["#6F263D", "#236192", "#A2AAAD"]], ["CBJ", "Columbus Blue Jackets", ["#002654", "#CE1126", "#A4A9AD"]],
  ["DAL", "Dallas Stars", ["#006847", "#8F8F8C", "#111111"]], ["DET", "Detroit Red Wings", ["#CE1126", "#FFFFFF"]],
  ["EDM", "Edmonton Oilers", ["#FF4C00", "#041E42"]], ["FLA", "Florida Panthers", ["#C8102E", "#041E42", "#B9975B"]],
  ["LAK", "Los Angeles Kings", ["#111111", "#A2AAAD"]], ["MIN", "Minnesota Wild", ["#154734", "#A6192E", "#EAAA00"]],
  ["MTL", "Montreal Canadiens", ["#AF1E2D", "#192168"]], ["NSH", "Nashville Predators", ["#FFB81C", "#041E42"]],
  ["NJD", "New Jersey Devils", ["#CE1126", "#000000"]], ["NYI", "New York Islanders", ["#00539B", "#F47D30"]],
  ["NYR", "New York Rangers", ["#0038A8", "#CE1126"]], ["OTT", "Ottawa Senators", ["#C52032", "#C2912C", "#000000"]],
  ["PHI", "Philadelphia Flyers", ["#F74902", "#000000"]], ["PIT", "Pittsburgh Penguins", ["#FCB514", "#000000"]],
  ["SJS", "San Jose Sharks", ["#006D75", "#EA7200", "#000000"]], ["SEA", "Seattle Kraken", ["#99D9D9", "#E9072B", "#001628"]],
  ["STL", "St. Louis Blues", ["#002F87", "#FCB514", "#041E42"]], ["TBL", "Tampa Bay Lightning", ["#002868", "#FFFFFF"]],
  ["TOR", "Toronto Maple Leafs", ["#00205B", "#FFFFFF"]], ["UTA", "Utah Mammoth", ["#69B3E7", "#010101", "#FFFFFF"]],
  ["VAN", "Vancouver Canucks", ["#00205B", "#00843D"]], ["VGK", "Vegas Golden Knights", ["#B4975A", "#333F42", "#C8102E"]],
  ["WSH", "Washington Capitals", ["#C8102E", "#041E42"]], ["WPG", "Winnipeg Jets", ["#004C97", "#AC162C", "#041E42"]],
];
export const teamColor = (ab: string) => TEAMS.find((t) => t[0] === ab)?.[2][0] ?? "#8e8e93";

type RGB = [number, number, number];
const rgbOf = (h: string): RGB => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as RGB;
const hexOf = (c: number[]) => "#" + c.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");
const lum = (c: number[]) => {
  const [r, g, b] = c.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }) as RGB;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const contrast = (a: number[], b: number[]) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
function hsl([r, g, b]: number[]): RGB {
  [r, g, b] = [r!, g!, b!].map((v) => v / 255);
  const mx = Math.max(r!, g!, b!), mn = Math.min(r!, g!, b!), l = (mx + mn) / 2, d = mx - mn;
  if (!d) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = mx === r ? ((g! - b!) / d + 6) % 6 : mx === g ? (b! - r!) / d + 2 : (r! - g!) / d + 4;
  return [h * 60, s, l];
}
function fromHsl([h, s, l]: RGB): RGB {
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = l - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [r, g, b].map((v) => (v + m) * 255) as RGB;
}
const chromatic = (c: number[]) => { const [, s, l] = hsl(c); return s >= 0.2 && l > 0.08 && l < 0.92; };

const hueGap = (a: number[], b: number[]) => { const d = Math.abs(hsl(a)[0] - hsl(b)[0]) % 360; return Math.min(d, 360 - d); };
const mix = (a: number[], b: number[], t: number) => a.map((v, i) => v + (b[i]! - v) * t);

/** Base surfaces per mode; a team theme tints them. Keep in sync with :root in index.css. */
export const BASE = {
  dark: { bg: "#080a10", surface: "#121621", surface2: "#1a1f2c" },
  light: { bg: "#eef1f6", surface: "#ffffff", surface2: "#f2f4f8" },
};

/** Move a color's lightness away from the surfaces until it reaches `min` contrast with every one. */
function readable(c: number[], surfaces: number[][], min: number, mode: "light" | "dark"): number[] {
  const [h, s, l0] = hsl(c), dir = mode === "dark" ? 1 : -1;
  for (let l = l0; l >= 0 && l <= 1; l += dir * 0.01) {
    const out = fromHsl([h, s, l]);
    if (surfaces.every((bg) => contrast(out, bg) >= min)) return out;
  }
  return mode === "dark" ? [255, 255, 255] : [0, 0, 0];
}

/** The whole palette for one team in one mode: tinted surfaces, accent, and the home/away series colors.
 *  Series colors keep 4.6:1 on every surface (labels are drawn in them; 4.6 leaves margin for hex rounding). */
export function teamPalette(colors: string[], mode: "light" | "dark"): Record<string, string> {
  const cs = colors.map(rgbOf), c1 = cs.find(chromatic) ?? cs[0]!;
  const c2raw = cs.find((c) => c !== c1 && chromatic(c) && hueGap(c, c1) >= 35);
  const b = BASE[mode], t = mode === "dark" ? 1 : 0.5;
  const bg = mix(rgbOf(b.bg), c1, 0.07 * t), surface = mix(rgbOf(b.surface), c1, 0.06 * t), surface2 = mix(rgbOf(b.surface2), c1, 0.08 * t);
  const surfaces = [bg, surface, surface2];
  const home = readable(c1, surfaces, 4.6, mode);
  let away: number[];
  if (c2raw) away = readable(c2raw, surfaces, 4.6, mode);
  else {
    // one-color team: the away series is the same hue pushed further from the surfaces, so the two still separate by lightness
    const [h, s, l] = hsl(home), l2 = mode === "dark" ? Math.min(0.92, l + 0.22) : Math.max(0.12, l - 0.2);
    away = fromHsl([(h + 25) % 360, Math.max(0.35, s), l2]);
  }
  const rgb = (c: number[]) => c.map(Math.round).join(" ");
  return {
    "--bg": hexOf(bg), "--surface-solid": hexOf(surface), "--surface-2": hexOf(surface2),
    "--accent": hexOf(home), "--accent-ink": contrast(home, [255, 255, 255]) >= 4.5 ? "#ffffff" : "#000000",
    "--home": hexOf(home), "--away": hexOf(away),
    "--glow-a": rgb(c1), "--glow-b": rgb(c2raw ?? away),
  };
}
