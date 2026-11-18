import { spawn } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { buildBrowserWorker } from "./build-browser-worker.mjs";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const platformRoot = resolve(webRoot, "../backend");
const python = process.env.PLATFORM_PYTHON || "python3";
const vinext = join(webRoot, "node_modules", ".bin", "vinext");
const commonEnvironment = { ...process.env, PYTHONDONTWRITEBYTECODE: "1" };

await buildBrowserWorker();

const api = process.env.ENABLE_LOCAL_DISCOVERY_API === "1" ? spawn(python, ["-B", "-m", "research_platform.discovery_api"], {
  cwd: platformRoot,
  env: { ...commonEnvironment, PYTHONPATH: join(platformRoot, "src") },
  stdio: "inherit",
}) : null;

const web = spawn(vinext, ["dev"], {
  cwd: webRoot,
  env: { ...commonEnvironment, WRANGLER_LOG_PATH: ".wrangler/wrangler.log" },
  stdio: "inherit",
});

let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  if (api && !api.killed) api.kill("SIGTERM");
  if (!web.killed) web.kill("SIGTERM");
  setTimeout(() => process.exit(code), 250);
}

api?.on("exit", (code) => {
  if (!stopping && code !== 0) stop(code ?? 1);
});
web.on("exit", (code) => stop(code ?? 0));
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));
