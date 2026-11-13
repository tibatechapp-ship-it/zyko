#!/usr/bin/env bash
# run_wave23_chunk.sh — غلاف التشغيلة المتنفّسة (الموجة 23): البروتوكول أمر
# واحد بلاستينياً — الجسر يُشغَّل ويُقتل داخل الاستدعاء نفسه، والمنصرف يُعاد
# جدولته عند التعافي (عقد التنفّس: --resume --retry-incomplete).
#
# Usage (docs/PROTOCOL.md §7):
#   bash scripts/run_wave23_chunk.sh benchmarks/results/swebench_full_wide23.json 540
#   bash scripts/run_wave23_chunk.sh <out.json> <id1[,id2,...]>
#
# العقد في هذا الغلاف:
#   1) الجسر المتنفّس يعيش داخل الاستدعاء فقط — يُقتل على الخروج مهما كانت النتيجة.
#   2) الإيقاع معلن: --pace-s 10 بين الحالات، وفاصل الجسر BRIDGE_MIN_INTERVAL_MS (20ث).
#   3) --resume --retry-incomplete: المكتمل = رقعة مطبَّقة فعلاً — المنصرف الخانق
#      يُعاد جدولته، ووثيقة واحدة لكل حالة (merge_result، الموجة 23).

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

OUT="${1:?usage: run_wave23_chunk.sh <out.json> <ids 540[,541,...]>}"
IDS="${2:?usage: run_wave23_chunk.sh <out.json> <ids 540[,541,...]>}"

BRIDGE_PORT="${BRIDGE_PORT:-8643}"
BRIDGE_MIN_INTERVAL_MS="${BRIDGE_MIN_INTERVAL_MS:-20000}"
BRIDGE_LOG="${BRIDGE_LOG:-benchmarks/results/bridge_$(date +%Y%m%d_%H%M%S).jsonl}"
export BRIDGE_PORT BRIDGE_MIN_INTERVAL_MS BRIDGE_LOG

echo "[wave23-chunk] الجسر يقلع: port=${BRIDGE_PORT} فاصل=${BRIDGE_MIN_INTERVAL_MS}ms سجل=${BRIDGE_LOG}"
node scripts/bridge.mjs &
BRIDGE_PID=$!
cleanup() {
  kill "$BRIDGE_PID" 2>/dev/null || true
  wait "$BRIDGE_PID" 2>/dev/null || true
}
trap cleanup EXIT

# جاهزية الجسر قبل أول نداء (healthz حتى 15ث)
ready=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${BRIDGE_PORT}/healthz" >/dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [[ "$ready" != "1" ]]; then
  echo "[wave23-chunk] الجسر لم يجهز — فشل سريع، انظر السجل: ${BRIDGE_LOG}" >&2
  exit 4
fi

echo "[wave23-chunk] التشغيلة: out=${OUT} ids=${IDS}"
ZYKO_QWEN_HOST="http://127.0.0.1:${BRIDGE_PORT}/v1" \
ZYKO_QWEN_API_KEY="${ZYKO_QWEN_API_KEY:-local-bridge}" \
PYTHONPATH=src python3 scripts/run_swebench_lite.py \
  --out "$OUT" \
  --ids "$IDS" \
  --pace-s 10 \
  --resume \
  --retry-incomplete

echo "[wave23-chunk] اكتملت التشغيلة — الجسر يُقتل الآن (بلاستينية)، أعد الأمر حتى «لا حالات متبقية»."
