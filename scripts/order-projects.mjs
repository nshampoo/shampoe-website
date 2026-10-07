// Orders the workshop rows in site/index.html newest first, using GitHub instead of hand-typed dates:
//   1. repo creation date (each row's data-repo="owner/name"), newest first
//   2. ties: my most recent commit to the repo, newest first
//   3. rows with no data-repo, or whose repo GitHub can't see (private), go last in their current order
// Runs before every deploy (npm run deploy in infra/). If GitHub can't be reached, the file is left as is.
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const GITHUB_USER = "nshampoo";
const file = join(dirname(fileURLToPath(import.meta.url)), "../site/index.html");
const html = readFileSync(file, "utf8");
const m = html.match(/(<!-- projects -->\n)([\s\S]*?)(\n<!-- \/projects -->)/);
if (!m) throw new Error("no <!-- projects --> markers in site/index.html");

const rows = [...m[2].matchAll(/[ \t]*<article[\s\S]*?<\/article>/g)].map(([block], i) => ({ block, i, repo: block.match(/data-repo="([^"]+)"/)?.[1] }));

async function gh(path) {
  const res = await fetch(`https://api.github.com/${path}`, { headers: { Accept: "application/vnd.github+json" } });
  if (res.status === 404) return null; // private or gone: sorts last
  if (!res.ok) throw new Error(`GitHub ${res.status} for ${path}`);
  return res.json();
}

try {
  for (const r of rows) {
    if (!r.repo) continue;
    const repo = await gh(`repos/${r.repo}`);
    if (!repo) continue;
    r.created = repo.created_at;
    const commits = await gh(`repos/${r.repo}/commits?author=${GITHUB_USER}&per_page=1`);
    r.committed = commits?.[0]?.commit.author.date ?? "";
  }
} catch (e) {
  console.warn(`order-projects: ${e.message}; leaving the order as is`);
  process.exit(0);
}

rows.sort((a, b) =>
  (!a.created - !b.created) ||
  (b.created ?? "").localeCompare(a.created ?? "") ||
  (b.committed ?? "").localeCompare(a.committed ?? "") ||
  a.i - b.i);

const after = html.replace(m[0], m[1] + rows.map((r) => r.block).join("\n\n") + m[3]);
for (const r of rows) console.log(`${(r.created ?? "no repo").slice(0, 10).padEnd(10)}  ${r.repo ?? r.block.match(/<h2[^>]*>.*?<a [^>]*>([^<]+)/)[1]}`);
if (after !== html) { writeFileSync(file, after); console.log("order-projects: reordered site/index.html"); }
else console.log("order-projects: order unchanged");
