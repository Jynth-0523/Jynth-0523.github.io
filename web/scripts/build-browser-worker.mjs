import { writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourcePath = resolve(webRoot, "app/factor-discovery.worker.ts");
const outputPath = resolve(webRoot, "public/factor-discovery.worker.js");

export async function buildBrowserWorker() {
  const compiled = await build({
    configFile: false,
    logLevel: "warn",
    build: {
      write: false,
      target: "es2020",
      minify: false,
      lib: { entry: sourcePath, name: "FactorDiscoveryWorker", formats: ["iife"] },
    },
  });
  const outputs = (Array.isArray(compiled) ? compiled : [compiled]).flatMap((result) => result.output);
  const chunks = outputs.filter((output) => output.type === "chunk");
  if (chunks.length !== 1) throw new Error("The browser worker must produce exactly one self-contained bundle.");
  await writeFile(outputPath, `/* Generated from app/factor-discovery.worker.ts and app/discovery/. Do not edit. */\n${chunks[0].code}`, "utf8");
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await buildBrowserWorker();
}
