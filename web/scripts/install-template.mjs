// Copy the built page over the template that report/build.py fills with data.
import { readFileSync, writeFileSync } from "node:fs";

const html = readFileSync(new URL("../dist/index.html", import.meta.url), "utf8");
if (!html.includes("/*__DATA__*/null")) throw new Error("payload placeholder missing from the build");
const bad = html.search(/[^\x00-\x7F]/);
if (bad >= 0) throw new Error(`non-ASCII character in the build near: ${html.slice(bad - 40, bad + 40)}`);
writeFileSync(new URL("../../src/nhlmodel/report/template.html", import.meta.url), html);
console.log(`template.html: ${(html.length / 1024).toFixed(0)} KB`);
