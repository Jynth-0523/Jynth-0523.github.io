#!/usr/bin/env node
// Resolve every application path from this file, not the caller's directory.
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = dirname(fileURLToPath(import.meta.url));
const web = join(root, "web");
const args = process.argv.slice(2);
if (args.includes("--help")) {
  console.log("Usage: node start-platform.mjs [--install | --check]\n--install: install locked web dependencies, then start\n--check: check prerequisites without starting a server");
  process.exit(0);
}
if (args.some((value) => !["--install", "--check"].includes(value))) {
  console.error("Unknown option. Use --help.");
  process.exit(2);
}
const [major, minor] = process.versions.node.split(".").map(Number);
if (major < 22 || (major === 22 && minor < 13)) {
  console.error("Node.js 22.13 or newer is required.");
  process.exit(2);
}
if (args.includes("--install") && !args.includes("--check")) {
  const install = spawnSync(process.platform === "win32" ? "npm.cmd" : "npm", ["ci"], {
    cwd: web, stdio: "inherit", shell: process.platform === "win32",
  });
  if (install.error || install.status !== 0) {
    console.error(install.error?.message || "Dependency installation did not finish successfully.");
    process.exit(install.status || 1);
  }
}
if (!existsSync(join(web, "node_modules", "vinext", "dist", "cli.js"))) {
  console.error("Web dependencies are missing. Run: node start-platform.mjs --install");
  process.exit(2);
}
if (args.includes("--check")) {
  console.log("Ready: Node.js and web dependencies are available. No private data or database is required.");
  process.exit(0);
}
const result = spawnSync(process.execPath, [join(web, "scripts", "dev.mjs")], {
  cwd: web, stdio: "inherit", env: process.env,
});
if (result.error) console.error(result.error.message);
process.exit(result.status ?? (result.signal === "SIGINT" ? 0 : 1));
