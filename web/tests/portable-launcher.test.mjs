import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const launcher = fileURLToPath(new URL("../../start-platform.mjs", import.meta.url));

test("launcher still works after the project folder is relocated and renamed", () => {
  const directory = mkdtempSync(join(tmpdir(), "renamed platform "));
  try {
    copyFileSync(launcher, join(directory, "start-platform.mjs"));
    mkdirSync(join(directory, "web"));
    symlinkSync(fileURLToPath(new URL("../node_modules", import.meta.url)), join(directory, "web/node_modules"), process.platform === "win32" ? "junction" : "dir");
    const result = spawnSync(process.execPath, [join(directory, "start-platform.mjs"), "--check"], { cwd: tmpdir(), encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /Ready:/);
  } finally {
    rmSync(directory, { recursive: true });
  }
});

test("launcher finds the repository from an unrelated directory containing spaces", () => {
  const directory = mkdtempSync(join(tmpdir(), "platform launch test "));
  try {
    const result = spawnSync(process.execPath, [launcher, "--check"], { cwd: directory, encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /Ready:/);
  } finally {
    rmSync(directory, { recursive: true });
  }
});

test("launcher rejects unknown options without running a server", () => {
  const result = spawnSync(process.execPath, [launcher, "--not-an-option"], { encoding: "utf8" });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /Unknown option/);
});
