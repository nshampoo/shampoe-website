// Copies partials/header.html and partials/footer.html into every page under site/.
// Each page marks where they go:
//   <!-- header page="live" --> ... <!-- /header -->   (page = workshop | live | about | none)
//   <!-- footer --> ... <!-- /footer -->
// Run after editing a partial:  node scripts/sync-chrome.mjs
import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const header = readFileSync(join(root, "partials/header.html"), "utf8").trim();
const footer = readFileSync(join(root, "partials/footer.html"), "utf8").trim();

function pages(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? pages(p) : name.endsWith(".html") ? [p] : [];
  });
}

let changed = 0;
for (const file of pages(join(root, "site"))) {
  const before = readFileSync(file, "utf8");
  const after = before
    .replace(/<!-- header page="(\w+)" -->[\s\S]*?<!-- \/header -->/, (_, page) => {
      let h = header;
      for (const key of ["workshop", "live", "about"]) {
        h = h.replace(`{{${key}}}`, key === page ? ' aria-current="page"' : "");
      }
      return `<!-- header page="${page}" -->\n${h}\n<!-- /header -->`;
    })
    .replace(/<!-- footer -->[\s\S]*?<!-- \/footer -->/, `<!-- footer -->\n${footer}\n<!-- /footer -->`);
  if (after !== before) { writeFileSync(file, after); changed++; console.log("updated", file.slice(root.length + 1)); }
}
console.log(`${changed} page(s) updated`);
