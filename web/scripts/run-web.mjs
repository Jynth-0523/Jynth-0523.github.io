import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const mode = process.argv[2];
if (!["build", "start"].includes(mode)) throw new Error("Expected build or start.");
const child = spawnSync(process.execPath, [resolve(root, "node_modules/vinext/dist/cli.js"), mode], {
  cwd: root,
  env: { ...process.env, WRANGLER_LOG_PATH: resolve(root, ".wrangler/wrangler.log") },
  stdio: "inherit",
});
if (child.error) console.error(child.error.message);
process.exit(child.status ?? 1);
