#!/usr/bin/env node
/**
 * bridge.mjs — الجسر المتنفّس (الموجة 23): نقطة نهاية متوافقة مع OpenAI
 * فوق المزوّد المحلي (z-ai-web-dev-sdk أو نقطة منبع خارجية اختيارية).
 *
 * العقد الثلاثة المعلنة (docs/PROTOCOL.md §7 — docs/SWEBENCH_WAVE22 §3):
 *   1) طيران واحد (single-flight): نداء منبع واحد في الطيران في أي لحظة —
 *      نداء متزامن إضافي يُرفض فوراً بـ503 بلا طابور ولا انتظار.
 *   2) فاصل أدنى بين نداءات المنبع: BRIDGE_MIN_INTERVAL_MS (افتراضي 20ث) —
 *      النداء يُؤجَّل حتى يكتمل الفاصل، والانتظار معلن في السجل.
 *   3) فشل سريع على 429: استجابة المنبع 429 تمرّ كما هي فوراً —
 *      بلا إعادة محاولة داخلية إطلاقاً؛ من يعيد هو من يقرر.
 *
 * سجل JSONL (BRIDGE_LOG) هو مصدر التشخيص الوحيد — «بلا عدّاد = بلا ادعاء»
 * يسري على الجسر نفسه: كل قرار (خدمة، تأجيل، رفض طيران، مرور 429) سطر فيه.
 *
 * التشغيل:
 *   BRIDGE_PORT=8643 BRIDGE_MIN_INTERVAL_MS=20000 node scripts/bridge.mjs &
 *   curl -s http://127.0.0.1:8643/healthz
 */

import http from "node:http";
import process from "node:process";
import { appendFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const PORT = Number(process.env.BRIDGE_PORT || 8643);
// العقد الثاني: الفاصل الأدنى بين نداءات المنبع — افتراضي 20ث كما وثّقت الموجة 22
const MIN_INTERVAL_MS = Number(process.env.BRIDGE_MIN_INTERVAL_MS || 20000);
// منبع اختياري متوافق مع OpenAI؛ بلا منبع يخدم الجسر بالمزوّد المحلي z-ai-web-dev-sdk
const UPSTREAM_URL = process.env.BRIDGE_UPSTREAM || "";
const UPSTREAM_API_KEY = process.env.BRIDGE_UPSTREAM_API_KEY || "";
const DEFAULT_MODEL = process.env.BRIDGE_MODEL || "glm-4.7";
// سجل الجسر JSONL — مصدر التشخيص الوحيد
const BRIDGE_LOG =
  process.env.BRIDGE_LOG || "benchmarks/results/bridge_log.jsonl";

mkdirSync(dirname(BRIDGE_LOG), { recursive: true });

/** سطر تشخيص واحد لكل قرار — JSONL ملحق ذرّياً */
function bridge_log(event) {
  const line = JSON.stringify({ ts: new Date().toISOString(), ...event });
  appendFileSync(BRIDGE_LOG, line + "\n");
}

// حالة الطيران الواحد والفاصل الأدنى
let in_flight = 0;
let last_upstream_at = 0;
// فاصل التعاقب: نداءان متتاليان للمنبع لا يقتربان من MIN_INTERVAL_MS
async function respect_min_interval() {
  const now = Date.now();
  const elapsed = now - last_upstream_at;
  if (elapsed < MIN_INTERVAL_MS) {
    const wait_ms = MIN_INTERVAL_MS - elapsed;
    bridge_log({ kind: "interval_wait", wait_ms });
    await new Promise((r) => setTimeout(r, wait_ms));
  }
}

async function serve_locally(body) {
  // المزوّد المحلي: z-ai-web-dev-sdk (نفس ميناء الاستدلال المستخدم في الموجتين 21-22)
  const { default: ZAI } = await import("z-ai-web-dev-sdk");
  const zai = await ZAI.create();
  const payload = {
    messages: body.messages,
    model: body.model || DEFAULT_MODEL,
    temperature: body.temperature ?? 0.2,
    max_tokens: body.max_tokens ?? 4096,
  };
  const completion = await zai.chat.completions.create(payload);
  return completion;
}

async function serve_upstream(body) {
  const headers = { "Content-Type": "application/json" };
  if (UPSTREAM_API_KEY) headers.Authorization = `Bearer ${UPSTREAM_API_KEY}`;
  const res = await fetch(UPSTREAM_URL, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const text = await res.text();
  return { status: res.status, text };
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && (req.url === "/healthz" || req.url === "/")) {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, in_flight, min_interval_ms: MIN_INTERVAL_MS }));
    return;
  }
  if (req.method !== "POST" || !req.url.startsWith("/v1/")) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "OpenAI-compatible: POST /v1/chat/completions" }));
    return;
  }

  const chunks = [];
  for await (const c of req) chunks.push(c);
  let body;
  try {
    body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    res.writeHead(400, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "invalid JSON body" }));
    return;
  }

  // العقد الأول: طيران واحد — رفض فوري 503 بلا طابور
  if (in_flight > 0) {
    bridge_log({ kind: "reject_in_flight", url: req.url });
    res.writeHead(503, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "single-flight: upstream busy" }));
    return;
  }
  in_flight += 1;
  const t0 = Date.now();
  bridge_log({ kind: "accept", url: req.url, model: body.model || DEFAULT_MODEL });
  try {
    await respect_min_interval();
    let status = 200;
    let payload;
    if (UPSTREAM_URL) {
      const r = await serve_upstream(body);
      status = r.status;
      payload = r.text;
      if (status === 429) {
        // العقد الثالث: فشل سريع على 429 — يمرّ كما هو، بلا إعادة محاولة داخلية
        bridge_log({ kind: "upstream_429", upstream_status: 429, elapsed_ms: Date.now() - t0 });
        res.writeHead(429, { "Content-Type": "application/json" });
        res.end(payload);
        return;
      }
      bridge_log({ kind: "upstream_done", upstream_status: status, elapsed_ms: Date.now() - t0 });
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(payload);
      return;
    }
    const completion = await serve_locally(body);
    payload = { id: "bridge-local", object: "chat.completion", created: Math.floor(Date.now() / 1000), model: body.model || DEFAULT_MODEL, ...completion };
    bridge_log({ kind: "local_done", elapsed_ms: Date.now() - t0 });
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(payload));
  } catch (err) {
    const msg = String(err && err.message ? err.message : err);
    const is429 = /429|rate.?limit|quota/i.test(msg);
    bridge_log({ kind: is429 ? "upstream_429" : "error", error: msg, elapsed_ms: Date.now() - t0 });
    res.writeHead(is429 ? 429 : 502, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: msg }));
  } finally {
    in_flight -= 1;
    last_upstream_at = Date.now();
  }
});

server.listen(PORT, "127.0.0.1", () => {
  bridge_log({ kind: "listen", port: PORT, min_interval_ms: MIN_INTERVAL_MS, upstream: UPSTREAM_URL || "z-ai-web-dev-sdk(local)" });
  process.stdout.write(`bridge: 127.0.0.1:${PORT} — طيران واحد، فاصل ${MIN_INTERVAL_MS}ث، فشل سريع على 429، سجل ${BRIDGE_LOG}\n`);
});
