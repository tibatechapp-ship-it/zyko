"""The `zyko` command-line interface.

Built on argparse only — zero third-party CLI dependencies — so the exact
same command set works on Linux, Windows, macOS and Termux with nothing to
compile.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Sequence

from zyko.cli import commands as cmd
from zyko.cli import ui
from zyko.exceptions import ZykoError
from zyko.log import setup_logging
from zyko.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zyko",
        description=f"ZYKO v{__version__} — Universal AI Orchestration Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  zyko ask 'Explain MCP in one line' --explain\n"
            "  zyko route 'summarize this file'          # planning only, no API call\n"
            "  zyko ask 'hello' --demo                   # offline, no keys needed\n"
            "  zyko ask 'hello' --demo --receipt r.json  # ...and write a verifiable receipt\n"
            "  zyko verify r.json                        # recompute it offline, no trust needed\n"
            "  zyko serve --port 8787                    # OpenAI-compatible gateway\n"
            "  zyko mcp serve                            # expose ZYKO as an MCP server\n"
            "  zyko sessions list                        # inspect stored chat memory\n"
            "  zyko cost                                 # spend & governance report\n"
            "  zyko traces --last 20                     # built-in span log (observability)\n"
            "  zyko doctor                               # diagnose platform + keys\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"zyko {__version__}")
    parser.add_argument(
        "--log-level", default="WARNING", help="DEBUG/INFO/WARNING (default: WARNING)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def with_router(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--strategy", choices=["quality", "cost", "latency", "balanced"], default=None
        )
        p.add_argument("--policy", default=None, help="policy name or path (Policy-as-Code)")
        p.add_argument("--ledger", default=None, help="quality ledger JSON path")
        p.add_argument(
            "--demo", action="store_true", help="offline mock provider: no keys, no network"
        )

    # info / doctor / version
    sub.add_parser("info", help="platform, config and provider summary").set_defaults(
        func=cmd.cmd_info
    )
    sub.add_parser("doctor", help="diagnose environment, keys and local inference").set_defaults(
        func=cmd.cmd_doctor
    )
    sub.add_parser("version", help="print version and protocol info").set_defaults(
        func=cmd.cmd_version
    )

    # models
    p = sub.add_parser("models", help="list available models with scores")
    p.add_argument("provider", nargs="?", default=None)
    p.add_argument("--ledger", default=None)
    p.set_defaults(func=cmd.cmd_models)

    # ask
    p = sub.add_parser("ask", help="one-shot completion through the router")
    p.add_argument("prompt")
    p.add_argument("--model", default=None, help="provider/model or 'auto'")
    p.add_argument("--system", default=None)
    p.add_argument("--max-tokens", type=int, default=None)
    p.add_argument("--explain", action="store_true", help="print the routing decision")
    p.add_argument("--receipt", default=None, help="write the verification receipt to a JSON file")
    with_router(p)
    p.set_defaults(func=cmd.cmd_ask)

    # chat
    p = sub.add_parser("chat", help="interactive chat with session memory")
    p.add_argument("--session", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--system", default=None)
    p.add_argument("--max-tokens", type=int, default=None)
    with_router(p)
    p.set_defaults(func=cmd.cmd_chat)

    # route (planning only)
    p = sub.add_parser("route", help="show the routing plan (no API call)")
    p.add_argument("prompt", nargs="?", default="")
    p.add_argument("--json", action="store_true")
    with_router(p)
    p.set_defaults(func=cmd.cmd_route)

    # verify (offline receipt replay)
    p = sub.add_parser("verify", help="verify a routing receipt offline (recompute every score)")
    p.add_argument("receipt", help="receipt JSON written by `zyko ask ... --receipt FILE`")
    p.add_argument(
        "--ledger",
        default=None,
        help="quality ledger the receipt claims to come from (cross-checks quality scores)",
    )
    p.add_argument(
        "--tolerance",
        type=float,
        default=5e-4,
        help="float drift allowed (default 5e-4 — receipts round to 4 decimals)",
    )
    p.add_argument("--json", action="store_true", help="print the full report as JSON")
    p.set_defaults(func=cmd.cmd_verify)

    # serve
    p = sub.add_parser("serve", help="OpenAI-compatible gateway over the router")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--api-key", default=None, help="require this bearer token on /v1/*")
    p.add_argument(
        "--users",
        default=None,
        help="multi-user YAML (0.7.0): per-user keys, roles, rpm and daily budgets",
    )
    with_router(p)
    p.set_defaults(func=cmd.cmd_serve)

    # hash-key (gateway users files)
    p = sub.add_parser("hash-key", help="scrypt-hash an API key for a users file")
    p.add_argument(
        "--key",
        default=None,
        help="the key to hash (omit to be prompted without echo)",
    )
    p.set_defaults(func=cmd.cmd_hash_key)

    # policy
    p = sub.add_parser("policy", help="Policy-as-Code: check, show, redact")
    pol = p.add_subparsers(dest="policy_cmd", required=True)
    c = pol.add_parser("check", help="validate a policy file")
    c.add_argument("file")
    c.set_defaults(func=cmd.cmd_policy)
    c = pol.add_parser("show", help="display a policy (or the builtin default)")
    c.add_argument("name", nargs="?", default=None)
    c.set_defaults(func=cmd.cmd_policy)
    c = pol.add_parser("redact", help="demo redaction on arbitrary text")
    c.add_argument("text")
    c.add_argument("name", nargs="?", default=None)
    c.set_defaults(func=cmd.cmd_policy)

    # mcp
    p = sub.add_parser("mcp", help="MCP integration")
    m = p.add_subparsers(dest="mcp_cmd", required=True)
    m.add_parser("serve", help="expose ZYKO as an MCP server over stdio").set_defaults(
        func=cmd.cmd_mcp
    )
    c = m.add_parser("tools", help="list tools of an MCP server: zyko mcp tools -- <cmd...>")
    c.add_argument("command", nargs="*", help="command to spawn (use -- before it)")
    c.set_defaults(func=cmd.cmd_mcp)

    # run (agents)
    p = sub.add_parser("run", help="run an agent from a YAML definition")
    p.add_argument("agent")
    p.add_argument("task")
    p.add_argument("--trace", action="store_true", help="print the step table")
    with_router(p)
    p.set_defaults(func=cmd.cmd_run)

    # crew (sequential multi-agent pipeline)
    p = sub.add_parser("crew", help="run a sequential multi-agent crew from a YAML file")
    p.add_argument("file", help="crew YAML: steps of agents + task templates")
    p.add_argument(
        "--input",
        "-i",
        required=True,
        help="the crew-level task text every template sees as {task}",
    )
    p.add_argument("--trace", action="store_true", help="print the per-step table")
    p.add_argument("--json", action="store_true", help="print the full CrewResult as JSON")
    with_router(p)
    p.set_defaults(func=cmd.cmd_crew)

    # sessions (memory visibility)
    p = sub.add_parser("sessions", help="inspect stored chat sessions (SQLite memory)")
    ses = p.add_subparsers(dest="sessions_cmd", required=True)
    ses.add_parser("list", help="list sessions with message counts").set_defaults(
        func=cmd.cmd_sessions
    )
    c = ses.add_parser("show", help="print every message of a session")
    c.add_argument("session_id")
    c.set_defaults(func=cmd.cmd_sessions)
    c = ses.add_parser("rm", help="delete one or more sessions")
    c.add_argument("session_ids", nargs="+")
    c.set_defaults(func=cmd.cmd_sessions)
    c = ses.add_parser("clear", help="delete ALL sessions (requires --yes)")
    c.add_argument("--yes", action="store_true")
    c.set_defaults(func=cmd.cmd_sessions)

    # cost (governance visibility)
    p = sub.add_parser("cost", help="spend & governance report from the policy audit log")
    p.add_argument("--days", type=int, default=7, help="window size in days (0 = all history)")
    p.add_argument("--audit", default=None, help="audit JSONL path (default: the policy audit log)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd.cmd_cost)

    # cache (response cache visibility)
    p = sub.add_parser("cache", help="inspect or clear the policy-gated response cache")
    with_router(p)
    p.add_argument("--clear", action="store_true", help="drop every cached response")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd.cmd_cache)

    # traces (built-in observability)
    p = sub.add_parser("traces", help="inspect spans from the built-in trace log")
    p.add_argument("--last", type=int, default=20, help="show the last N spans (default 20)")
    p.add_argument("--trace", default=None, help="only spans of this trace id")
    p.add_argument("--file", default=None, help="trace JSONL path (default: data dir)")
    p.add_argument("--clear", action="store_true", help="delete the trace log")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd.cmd_traces)

    # bench
    p = sub.add_parser("bench", help="run the reproducible routing benchmark")
    p.add_argument(
        "--update-ledger", action="store_true", help="merge results into the quality ledger"
    )
    p.add_argument("--json-out", default=None, help="write full results JSON here")
    p.add_argument("--ledger", default=None)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="repeat the suite N times for stabler medians (default 1)",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="benchmark the offline mock provider (CI/pipeline check)",
    )
    p.set_defaults(func=cmd.cmd_bench)

    # new (coder — المرحلة 1: توليد مشروع من وصف عربي)
    p = sub.add_parser(
        "new",
        help="generate a project from an Arabic description (plan → approve → build)",
    )
    p.add_argument("--plan", "-p", required=True, help="الوصف العربي للمشروع")
    p.add_argument("--out", "-o", default=None, help="مجلد الإخراج (افتراضي: ./<name>)")
    p.add_argument("--name", default=None, help="تجاوز اسم المشروع في المخطط")
    p.add_argument(
        "--template",
        choices=["python-cli", "fastapi-api", "static-site"],
        default=None,
        help="تجاوز القالب المختار",
    )
    p.add_argument("--yes", "-y", action="store_true", help="الموافقة على المخطط دون سؤال")
    p.add_argument("--no-git", action="store_true", help="بلا git init والتزام أول")
    p.add_argument("--json", action="store_true", help="اعرض المخطط JSON فقط دون كتابة")
    p.add_argument("--run-tests", action="store_true", help="شغّل اختبارات المشروع بعد التوليد")
    p.set_defaults(func=cmd.cmd_new)

    # gauntlet (البناش: 1000 برنامج حقيقي تُبنى وتُختبر — إثبات القدرة)
    p = sub.add_parser(
        "gauntlet",
        help="الفحص الكبير: يبني 1000 مشروعًا حقيقيًا وينفّذ عينة حتمية باختباراتها الخاصة",
    )
    p.add_argument(
        "--per-intent",
        type=int,
        default=100,
        help="مخططات لكل نية (افتراضي 100 ⇒ 1000 برنامجًا على 10 نوايا)",
    )
    p.add_argument(
        "--execute",
        type=int,
        default=0,
        help="عدد البرامج التي تُنفّذ اختباراتها الحقيقية، موزعة حتميًا على النوايا (0 = فحص المصفوفة فقط)",
    )
    p.add_argument(
        "--all",
        dest="execute_all",
        action="store_true",
        help="نفّذ كل البرامج باختباراتها (مكلف: ‎~2 ثانية لكل برنامج)",
    )
    p.add_argument("--json-out", default=None, help="اكتب الإيصال الحتمي JSON هنا")
    p.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="طبقة الشدّ: كرر بناء المصفوفة كاملة N مرة وتحقق من تطابق البصمة بالبايت (‎>1 يفعّل طبقة الشدّ)",
    )
    p.add_argument(
        "--review-sample",
        type=int,
        default=0,
        help="طبقة الشدّ: راجع عينة حتمية من البرامج المولَّدة بمحرك المراجعة نفسه وتحقق من عتبة الجودة (‎>0 يفعّل طبقة الشدّ)",
    )
    p.add_argument(
        "--include-timing",
        action="store_true",
        help="أضف الزمن للإيصال (يكسر الحتمية البايتية)",
    )
    p.set_defaults(func=cmd.cmd_gauntlet)

    # compare (منصة المقارنة الحتمية: قياس zyko على جهازك + منافس اختياري صادق)
    p = sub.add_parser(
        "compare",
        help="المقارنة الحتمية: دقة التصنيف + سرعة المراجعة + الحتمية على هدف حقيقي، ومنافس اختياري بأمر تمرره أنت",
    )
    p.add_argument("target", help="الملف الحقيقي الذي تُقاس عليه السرعة والحتمية")
    p.add_argument(
        "--competitor-cmd",
        default=None,
        help="قالب أمر المنافس فيه {path} — مثال: «ruff check {path}» أو «pylint {path}» (اختياري: بدونه يوثَّق «لم يُشغَّل» بصدق)",
    )
    p.add_argument(
        "--runs",
        type=int,
        default=3,
        help="عدد التشغيلات لكل قياس (الحتمية تحتاج 2 على الأقل — الافتراضي 3)",
    )
    p.add_argument("--json-out", default=None, help="اكتب الإيصال الحتمي JSON هنا")
    p.add_argument(
        "--include-timing",
        action="store_true",
        help="أضف الأزمنة للإيصال (يكسر الحتمية البايتية)",
    )
    p.set_defaults(func=cmd.cmd_compare)

    # factory (المرحلة 7: بوابة المصنع الموحدة — تفويض حرفي لوحدات المحرك)
    p = sub.add_parser(
        "factory",
        help="بوابة المصنع الموحدة: map / fix / pipeline / workspace / gates / dashboard",
    )
    from zyko.factory.cli import register_to as _register_factory

    _register_factory(p.add_subparsers(dest="factory_cmd"))
    p.set_defaults(func=cmd.cmd_factory)

    # py (المرحلة 3: بوابة ضاد — المترجم العربي المستقل، تفويض بعملية منفصلة)
    p = sub.add_parser(
        "py",
        help="ترجم/نفّذ ملف .daad عبر مترجم ضاد المستقل (عملية منفصلة — لا استيراد داخلي)",
    )
    p.add_argument("file", help="مسار ملف .daad")
    p.add_argument("--out", "-o", default=None, help="اكتب بايثون المُولَّد إلى مسار مخصص")
    p.add_argument("--stdout", action="store_true", help="اطبع بايثون المُولَّد إلى الخرج القياسي")
    p.add_argument("--run", action="store_true", help="نفّذ البرنامج بعد الترجمة")
    p.add_argument("--check", action="store_true", help="فحص الصياغة فقط دون كتابة أو تنفيذ")
    p.set_defaults(func=cmd.cmd_py)

    # do (العقل: classify → route → run — الهدف النهائي: أمر واحد)
    p = sub.add_parser(
        "do",
        help="العقل يقرر: صنّف هدفك، خطّط، نفّذ — وضع تجريبي افتراضياً بلا أي كتابة",
    )
    p.add_argument("goal", help="الهدف بالعربية أو الإنجليزية — مثال: «راجع وأصلح src/main.py»")
    p.add_argument(
        "--dry-run", action="store_true", help="وضع تجريبي (افتراضي أصلاً — يظهر هنا للتوثيق)"
    )
    p.add_argument(
        "--write",
        action="store_true",
        help="طبّق الكتابة فعلياً (بدونه لا يُكتب أي ملف — قاعدة R9)",
    )
    p.add_argument("--path", default=None, help="فرض مسار الهدف بدل الاستخراج من النص")
    p.add_argument("--file", default=None, help="فرض ملف ضاد")
    p.add_argument("--src", default=None, help="فرض جذر التحليل لخط الأساس")
    p.add_argument("--description", default=None, help="فرض وصف المشروع المولَّد")
    p.add_argument("--receipt", default=None, help="اكتب الإيصال الموحّد إلى ملف JSON")
    p.add_argument("--json", action="store_true", help="اطبع الإيصال JSON فقط بلا سرد")
    p.add_argument(
        "--brain",
        choices=("ollama", "qwen"),
        default=None,
        help="اختياري: خطِّط بدماغ حقيقي خلف البوابات نفسها — الاقتراح يُتحقق حتميًا وأي فشل يرجع للمخطط الحتمي (بدونه: المخطط الحتمي فقط، بلا شبكة)",
    )
    p.add_argument(
        "--model",
        default=None,
        help="اسم النموذج (مطلوب مع --brain) — مثال: qwen2.5:7b أو qwen-plus",
    )
    p.add_argument(
        "--ollama-host",
        default=None,
        help="عنوان خادم Ollama مع --brain ollama (افتراضي ZYKO_OLLAMA_HOST أو 127.0.0.1:11434)",
    )
    p.add_argument(
        "--qwen-host",
        default=None,
        help="عنوان نقطة نهاية متوافقة مع OpenAI مع --brain qwen (افتراضي ZYKO_QWEN_HOST)؛ المفتاح من ZYKO_QWEN_API_KEY",
    )
    p.set_defaults(func=cmd.cmd_do)

    # ai (المرحلة 8: طبقة الذكاء فوق المصنع — جلسات موثّقة عبر البوابات)
    p = sub.add_parser(
        "ai",
        help="طبقة الذكاء فوق المصنع: map / run / gate",
    )
    from zyko.ai.cli import register_to as _register_ai

    _register_ai(p.add_subparsers(dest="ai_cmd"))
    p.set_defaults(func=cmd.cmd_ai)

    # mind (المرحلة A: الحلقة الإدراكية الكاملة — إدراك ← خطة ← تنفيذ ← نقد ← ذاكرة)
    p = sub.add_parser(
        "mind",
        help="نواة العقل المستقل: run / map",
    )
    from zyko.mind.cli import register_to as _register_mind

    _register_mind(p.add_subparsers(dest="mind_cmd"))
    p.set_defaults(func=cmd.cmd_mind)

    return parser


def _guard_output_encoding() -> None:
    """Never crash on characters the console cannot encode.

    Windows redirected output defaults to a legacy code page (cp1252 and
    friends): printing an em-dash or an Arabic answer used to raise
    UnicodeEncodeError and kill the command. ``errors="replace"`` keeps the
    command alive on every platform; UTF-8 terminals are unaffected.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):  # non-standard streams
            pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    # The guard MUST run before parse_args(): `zyko --help` prints the epilog
    # (which contains →) from inside parse_args, and on Windows pipes that
    # output is cp1252 — the old post-parse placement left --help and usage
    # errors as the one codepath that could still die with UnicodeEncodeError.
    _guard_output_encoding()
    args: Any = parser.parse_args(argv)
    quiet = not (getattr(args, "log_level", "WARNING") != "DEBUG")
    setup_logging(args.log_level if hasattr(args, "log_level") else "WARNING", quiet=quiet)
    try:
        result = args.func(args)
        return int(result or 0)
    except ZykoError as exc:
        ui.error(exc)
        return 1
    except BrokenPipeError:
        # Downstream closed the pipe (`zyko doctor | head`) — exit quietly
        # instead of spewing a traceback (standard POSIX CLI behavior).
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        return 141  # 128 + SIGPIPE — the conventional pipe exit code
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
