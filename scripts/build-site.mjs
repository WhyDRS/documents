import { readdirSync, mkdirSync, copyFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, extname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const output = join(root, "public");
const documents = [];
const ignoredDirectories = new Set([".git", ".netlify", "node_modules", "public"]);

function collect(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const source = join(directory, entry.name);
    if (entry.isDirectory()) {
      if (!entry.name.startsWith(".") && !ignoredDirectories.has(entry.name)) {
        collect(source);
      }
    } else if (entry.isFile() && [".md", ".pdf"].includes(extname(entry.name).toLowerCase())) {
      documents.push(relative(root, source));
    }
  }
}

function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function linkPart(value) {
  return encodeURIComponent(value);
}

function indexDirectory(folder, allFolders) {
  const here = join(output, folder);
  mkdirSync(here, { recursive: true });
  const childFolders = [...allFolders].filter((f) => dirname(f) === (folder || ".") && f !== folder)
    .sort((a, b) => a.localeCompare(b, "en"));
  const childDocuments = documents.filter((p) => dirname(p) === (folder || "."))
    .sort((a, b) => a.localeCompare(b, "en"));
  const items = [
    ...childFolders.map((f) => `<li><a href="${linkPart(f.split(sep).at(-1))}/">${escapeHtml(f.split(sep).at(-1))}/</a></li>`),
    ...childDocuments.map((p) => `<li><a href="${linkPart(p.split(sep).at(-1))}">${escapeHtml(p.split(sep).at(-1))}</a></li>`),
  ];
  const back = folder ? `<p><a href="../">Parent directory</a></p>` : "";
  const title = folder ? `WhyDRS Documents — ${folder}` : "WhyDRS Documents";
  const page = [
    "<!doctype html>",
    '<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
    `<title>${escapeHtml(title)}</title></head><body>`,
    `<h1>${escapeHtml(title)}</h1>${back}<ul>${items.join("")}</ul>`,
    "</body></html>",
  ].join("\n");
  writeFileSync(join(here, "index.html"), `${page}\n`, "utf8");
}

collect(root);
if (documents.length === 0) {
  throw new Error("No Markdown or PDF documents found; refusing to publish an empty site");
}
rmSync(output, { recursive: true, force: true });
mkdirSync(output, { recursive: true });
const folders = new Set([""]);
for (const document of documents) {
  const destination = join(output, document);
  mkdirSync(dirname(destination), { recursive: true });
  copyFileSync(join(root, document), destination);
  let folder = dirname(document);
  while (folder !== ".") {
    folders.add(folder);
    folder = dirname(folder);
  }
}
for (const folder of folders) {
  indexDirectory(folder, folders);
}
writeFileSync(join(output, "_headers"), [
  "/*.md",
  "  Content-Type: text/plain; charset=utf-8",
  "/*",
  "  X-Content-Type-Options: nosniff",
  "  X-Frame-Options: SAMEORIGIN",
  "",
].join("\n"), "utf8");
console.log(`Published ${documents.length} documents into ${folders.size} browseable directories.`);
