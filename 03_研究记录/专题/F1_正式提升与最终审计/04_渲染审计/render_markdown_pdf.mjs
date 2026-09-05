#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const [inputArgument, outputDirectoryArgument, outputStem] = process.argv.slice(2);
if (!inputArgument || !outputDirectoryArgument || !outputStem) {
  throw new Error(
    "usage: render_markdown_pdf.mjs INPUT.md OUTPUT_DIRECTORY OUTPUT_STEM",
  );
}

const input = path.resolve(inputArgument);
const outputDirectory = path.resolve(outputDirectoryArgument);
const html = path.join(outputDirectory, `${outputStem}.html`);
const pdf = path.join(outputDirectory, `${outputStem}.pdf`);
const metrics = path.join(outputDirectory, `${outputStem}.render.json`);
const stylesheet = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "render.css",
);
const servedStylesheet = path.join(outputDirectory, "render.css");
const pandoc = process.env.PANDOC_BIN || "/usr/bin/pandoc";
const chrome = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const mathjax = process.env.MATHJAX_JS;

if (!mathjax || !fs.existsSync(mathjax)) {
  throw new Error("MATHJAX_JS must name an existing local MathJax tex-chtml.js");
}
fs.mkdirSync(outputDirectory, { recursive: true });
fs.copyFileSync(stylesheet, servedStylesheet);
const mathjaxRelative = path.relative(outputDirectory, path.resolve(mathjax));
if (mathjaxRelative.startsWith("..") || path.isAbsolute(mathjaxRelative)) {
  throw new Error("MATHJAX_JS must be inside OUTPUT_DIRECTORY for local serving");
}

const pandocResult = spawnSync(
  pandoc,
  [
    "--from=markdown",
    "--to=html5",
    "--standalone",
    `--mathjax=${mathjaxRelative.split(path.sep).join("/")}`,
    "--css=render.css",
    `--metadata=pagetitle:${path.basename(input)}`,
    `--output=${html}`,
    input,
  ],
  { encoding: "utf8" },
);
if (pandocResult.status !== 0) {
  throw new Error(`Pandoc failed: ${pandocResult.stderr || pandocResult.stdout}`);
}
const generatedHtml = fs
  .readFileSync(html, "utf8")
  .replace(
    /\s*<script src="https:\/\/polyfill\.io\/v3\/polyfill\.min\.js\?features=es6"><\/script>/,
    "",
  );
if (
  /\bsrc="https?:\/\//.test(generatedHtml) ||
  /<link\b[^>]*\bhref="https?:\/\//.test(generatedHtml)
) {
  throw new Error("generated HTML contains a non-local external resource");
}
fs.writeFileSync(html, generatedHtml, "utf8");

const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".woff": "font/woff",
};
const server = http.createServer((request, response) => {
  const requestPath = decodeURIComponent(
    new URL(request.url || "/", "http://127.0.0.1").pathname,
  );
  if (requestPath === "/favicon.ico") {
    response.writeHead(204).end();
    return;
  }
  const requested = path.resolve(outputDirectory, `.${requestPath}`);
  if (
    requested !== outputDirectory &&
    !requested.startsWith(`${outputDirectory}${path.sep}`)
  ) {
    response.writeHead(403).end("forbidden");
    return;
  }
  if (!fs.existsSync(requested) || !fs.statSync(requested).isFile()) {
    response.writeHead(404).end("not found");
    return;
  }
  response.writeHead(200, {
    "Content-Type": mimeTypes[path.extname(requested)] || "application/octet-stream",
  });
  fs.createReadStream(requested).pipe(response);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
if (!address || typeof address === "string") throw new Error("local server failed");

const browser = await chromium.launch({
  executablePath: chrome,
  headless: true,
  args: ["--font-render-hinting=none"],
});
const browserErrors = [];
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
  page.setDefaultNavigationTimeout(120_000);
  page.setDefaultTimeout(300_000);
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.goto(`http://127.0.0.1:${address.port}/${path.basename(html)}`, {
    waitUntil: "commit",
  });
  await page.waitForFunction(() => document.readyState !== "loading");
  const sourceMathCount = await page.locator("span.math, div.math").count();
  if (sourceMathCount > 0) {
    await page.waitForFunction(() => globalThis.MathJax?.startup?.promise);
    await page.evaluate(async () => globalThis.MathJax.startup.promise);
  }
  await page.evaluate(async () => document.fonts.ready);

  const observations = await page.evaluate(() => {
    const mathSources = document.querySelectorAll("span.math, div.math").length;
    const mathContainers = document.querySelectorAll("mjx-container").length;
    const images = [...document.images].map((image) => ({
      complete: image.complete,
      naturalHeight: image.naturalHeight,
      naturalWidth: image.naturalWidth,
      src: image.src,
    }));
    const horizontalOverflow = [...document.querySelectorAll("body *")]
      .filter((element) => {
        const style = getComputedStyle(element);
        if (style.position === "fixed" || style.display === "inline") return false;
        return element.scrollWidth > element.clientWidth + 2;
      })
      .slice(0, 20)
      .map((element) => ({
        className: String(element.className || ""),
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        tagName: element.tagName,
        text: String(element.textContent || "").trim().slice(0, 120),
      }));
    return {
      documentHorizontalOverflow:
        document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      horizontalOverflow,
      imageCount: images.length,
      images,
      mathContainers,
      mathErrors: document.querySelectorAll(
        "mjx-merror, .MathJax_Error, [data-mjx-error]",
      ).length,
      mathSources,
      title: document.title,
    };
  });

  await page.pdf({
    path: pdf,
    format: "A4",
    printBackground: true,
    preferCSSPageSize: true,
  });

  const result = {
    ...observations,
    browserErrors,
    chrome,
    html,
    input,
    mathjax: path.resolve(mathjax),
    pandoc,
    pdf,
    status:
      observations.mathSources === observations.mathContainers &&
      observations.mathErrors === 0 &&
      observations.images.every(
        (image) => image.complete && image.naturalHeight > 0 && image.naturalWidth > 0,
      ) &&
      browserErrors.length === 0 &&
      !observations.documentHorizontalOverflow
        ? "PASS"
        : "FAIL",
  };
  fs.writeFileSync(metrics, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(result)}\n`);
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
