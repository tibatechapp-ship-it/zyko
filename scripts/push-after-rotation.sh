#!/usr/bin/env bash
# Push protocol — token never touches disk, git config, argv, or the repo.
#
# Usage:  GH_PUSH_TOKEN='<token>' bash scripts/push-after-rotation.sh
#
# Protocol invariants:
#   1. The token exists ONLY inside the GH_PUSH_TOKEN env var of this
#      single shell invocation. It is never written to any file.
#   2. The credential helper below is attached with `git -c` for THIS
#      command only — nothing persists in .git/config.
#   3. The burn list records prefixes (first 8 chars) of DEAD tokens that
#      the user must revoke on GitHub. The active token is NEVER listed
#      here until the task is finished, then it is added by prefix only.
#   4. --follow-tags carries annotated tags so releases never split from
#      the commit they certify.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "${GH_PUSH_TOKEN:-}" ]]; then
  echo "FATAL: GH_PUSH_TOKEN not set in this shell (env-only protocol)" >&2
  exit 2
fi

# ---- burn-list guard -------------------------------------------------------
# Prefixes of tokens that are dead/superseded. If the active credential
# matches one of these, refuse to push.
BURN_LIST=(
  "ghp_YgW"   # 1  superseded
  "ghp_Irk"   # 2  superseded
  "ghp_skZ"   # 3  superseded
  "ghp_kOf"   # 4  superseded
  "ghp_b5s"   # 5  superseded
  "ghp_m2t"   # 6  superseded
  "ghp_Rlom"  # 7  superseded
  "ghp_7tfQ"  # 8  confirmed revoked (401)
  "ghp_exe"   # 9  superseded
  "ghp_vF3g"  # 10 superseded
  "ghp_RBTU"  # 11 superseded
  "ghp_m3OR"  # 12 superseded
  "ghp_jKzq"  # 13 superseded
  "ghp_T3HT"  # 14 superseded, never used
  "ghp_v1kh"  # 15 superseded by 16th delivery
  "ghp_SEUG"  # 16 dead on arrival (401 Bad credentials, verified twice) — user must revoke
  "ghp_2R5w"  # 17 burned after publishing 0.46.0 + 0.47.0 cycles — user must revoke
  "ghp_U5Zk"  # 18 burned after publishing 0.48.0 (wave 25 path rescuer) — user must revoke
  "ghp_OtG9"  # 19 burned after publishing 0.49.0 + 0.50.0 (waves 26 reverse-map + 27 hybrid review) — user must revoke
  "ghp_vwdO"  # 20 burned after publishing 0.51.0 (wave 28 graph-planning feed + audit-before-counting gate) — user must revoke
  "ghp_wCBo"  # 21 burned after publishing 0.52.0 (wave 29 static gate in repair loop + patch text archiving) — user must revoke
)

PREFIX="${GH_PUSH_TOKEN:0:8}"
for dead in "${BURN_LIST[@]}"; do
  # مُضاية بالبادئة لا مساواة: قائمة التاريخ تحمل بادئات من 7 أحرف،
  # والحراسة تنكسر لو تطلبت طولًا موحدًا — أي توكن يبدأ ببادئة ميتة مرفوض.
  if [[ "$PREFIX" == "$dead"* ]]; then
    echo "FATAL: active token matches burn-list prefix $dead — refusing to push." >&2
    exit 3
  fi
done

# ---- push with transient credential helper ---------------------------------
git -C "$REPO" \
  -c credential.helper='!f() { printf "username=x-access-token\npassword=%s\n" "$GH_PUSH_TOKEN"; }; f' \
  push origin main --follow-tags

unset GH_PUSH_TOKEN
echo "push complete; credential var unset in this shell."
