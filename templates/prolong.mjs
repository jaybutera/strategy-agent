#!/usr/bin/env node
// Raw log for interactive sessions in this campaign, PRO-LONG style.
//
// Registered as a Claude Code hook for SessionStart, UserPromptSubmit,
// PostToolUse, Stop and SessionEnd. Reads the hook event JSON on stdin,
// appends one line to raw/<holder>/sessions/<date>.jsonl, prints {}.
//
// It lives under .sa/ rather than in the directory a global PRO-LONG install
// uses, on purpose: those global hooks would otherwise also fire in this
// campaign and log every session twice, into a directory git does not track.
import { appendFileSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const LIMIT = 4096; // bytes of tool-result text kept; the rest is a count

function holder() {
  try {
    const t = execFileSync("git", ["-C", ROOT, "config", "--get", "sa.holder"],
                           { encoding: "utf8" }).trim();
    if (t) return t;
  } catch { /* not a git checkout, or no token set */ }
  return (process.env.SA_HOLDER || "").trim() || "_unknown";
}

function eventType(event) {
  const name = String(event?.hook_event_name ?? event?.type ?? "event");
  const lower = name.toLowerCase();
  if (lower.includes("session") && (lower.includes("start") || lower.includes("created"))) return "session_start";
  if (lower.includes("session") && (lower.includes("end") || lower.includes("shutdown") || lower.includes("idle"))) return "session_end";
  if (lower.includes("prompt") || (lower.includes("message") && event?.message?.role === "user")) return "user_prompt";
  if (lower.includes("tool") && (lower.includes("result") || lower.includes("after") || lower.includes("end") || lower.includes("post"))) return "tool_result";
  if (lower.includes("tool")) return "tool_call";
  if (lower.includes("stop") || (lower.includes("message") && event?.message?.role === "assistant")) return "assistant_message";
  return name;
}

function json(value) {
  const seen = new WeakSet();
  return JSON.stringify(value, (_k, v) => {
    if (typeof v === "bigint") return v.toString();
    if (typeof v === "object" && v !== null) {
      if (seen.has(v)) return "[circular]";
      seen.add(v);
    }
    return v;
  });
}

// A Read result is dropped: the file at that commit is the record. Anything
// else over LIMIT keeps its head and reports how much was dropped.
function shrink(event) {
  const resp = event?.tool_response ?? event?.toolResponse;
  if (resp === undefined) return event;
  if (String(event?.tool_name ?? event?.toolName) === "Read") {
    const p = event?.tool_input?.file_path ?? event?.tool_input?.path ?? null;
    return { ...event, tool_response: { elided: "Read", path: p } };
  }
  const text = typeof resp === "string" ? resp : json(resp) ?? "";
  const bytes = Buffer.from(text, "utf8");
  if (bytes.length <= LIMIT) return event;
  return { ...event, tool_response: { head: bytes.subarray(0, LIMIT).toString("utf8"),
                                      elided: bytes.length - LIMIT } };
}

function main(raw) {
  if (process.env.SA_TICK) return;      // ticks are transcribed by sa loop
  const event = raw.trim() === "" ? {} : JSON.parse(raw);
  const type = eventType(event);
  if (type === "tool_call" || type === "tool_result") {
    // never log our own writes
    if ((json(event?.tool_input) ?? "").includes("raw/")) return;
  }
  const now = new Date();
  const dir = path.join(ROOT, "raw", holder(), "sessions");
  const entry = { timestamp: now.toISOString(),
                  sessionId: event?.session_id ?? event?.sessionId ?? null,
                  type, content: shrink(event) };
  mkdirSync(dir, { recursive: true });
  appendFileSync(path.join(dir, `${now.toISOString().slice(0, 10)}.jsonl`),
                 `${json(entry)}\n`, "utf8");
}

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => { input += c; });
process.stdin.on("end", () => {
  // A logger must never break the session it logs.
  try { main(input); } catch (e) { process.stderr.write(`sa prolong: ${e?.message ?? e}\n`); }
  process.stdout.write("{}");
  process.exit(0);
});
