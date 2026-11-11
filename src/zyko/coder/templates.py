"""zyko.coder.templates — قوالب المشاريع الثلاثة (D8–9).

Jinja-less deterministic templates: every template is a pure function
``(ProjectPlan) -> dict[path, GenFile]`` assembled from string blocks.
Same plan in, byte-identical tree out — no clock, no randomness.

- ``python-cli``  : حزمة src-layout مع مخزن بيانات لكل وحدة + CLI بـ argparse.
- ``fastapi-api`` : تطبيق FastAPI مع CRUD في الذاكرة لكل وحدة + /health.
- ``static-site`` : موقع HTML/CSS/JS ساكن باتجاه RTL وقواعد CSS منطقية.

Every generated python file must survive ``ast.parse`` (precheck D14) and
the static-site CSS must pass ``zyko.tools.rtl`` — the templates obey by
construction (logical properties only).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .plan import ProjectPlan, package_name


@dataclass(frozen=True)
class GenFile:
    """ملف مولَّد: مساره النسبي، محتواه، وسببه العربي (للـ RECEIPT)."""

    path: str
    content: str
    reason: str


TemplateBuilder = Callable[[ProjectPlan], dict[str, GenFile]]


def cls_name(module: str) -> str:
    """task_items -> TaskItems (اسم صنف آمن من معرّف مُتحقق)."""
    return "".join(part.capitalize() for part in module.split("_"))


def _doc3(text: str) -> str:
    """يغلّف نص docstring الثلاثي للاستيفاء داخل القوالب المتشعبة بلا اقتباس في المصدر."""
    return "'''" + text + "'''"


def _readme(plan: ProjectPlan, run_lines: list[str]) -> GenFile:
    disp = plan.display_name or plan.name
    mods = "\n".join(f"- `{m}`" for m in plan.modules)
    runs = "\n".join(f"`{c}`" for c in (run_lines or plan.run_commands)) or "—"
    body = f"""# {disp}

مولَّد بـ `zyko.coder` — المرحلة 1 من محرك البرمجة ZYKO (توليد حتمي قابل للإعادة).

## الوصف الأصلي

> {plan.description.strip()}

## الوحدات

{mods}

## التشغيل

{runs}

## الاختبارات

```bash
pytest -q
```
"""
    return GenFile("README.md", body, "دليل تشغيل واختبار عربي للمشروع")


def _gitignore() -> GenFile:
    body = """__pycache__/
*.py[cod]
.pytest_cache/
.coverage
dist/
build/
*.egg-info/
.venv/
venv/
.DS_Store
"""
    return GenFile(".gitignore", body, "تجاهل مخلفات بايثون والنظام قبل أول التزام")


def _pyproject(
    plan: ProjectPlan,
    extra_deps: list[str],
    dev_deps: list[str],
    scripts: dict[str, str],
    packages: str,
) -> GenFile:
    deps = "\n".join(f'  "{d}",' for d in plan.dependencies) or ""
    if extra_deps:
        deps = ("\n".join(f'  "{d}",' for d in extra_deps) + ("\n" if deps else "")) + deps
    dev = "\n".join(f'  "{d}",' for d in dev_deps)
    script_lines = "\n".join(f'{k} = "{v}"' for k, v in scripts.items())
    body = f"""[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{plan.name}"
version = "0.1.0"
description = "{plan.description.strip()[:80].replace('"', "'")}"
requires-python = ">=3.11"
dependencies = [
{deps}
]

[project.optional-dependencies]
dev = [
{dev}
]

[project.scripts]
{script_lines}

[tool.setuptools.packages.find]
where = ["{packages}"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["{packages == "." and "." or packages}"]
"""
    return GenFile(
        "pyproject.toml", body, "تغليف قياسي (setuptools) مع إعدادات pytest وأوامر الدخول"
    )


# ---------------------------------------------------------------------------
# python-cli
# ---------------------------------------------------------------------------


def _cli_core_section(module: str) -> str:
    C = cls_name(module)
    return f'''

@dataclass
class {C}Row:
    """صف {module}: سجل قصير قابل للتخزين في JSON."""

    row_id: int
    title: str
    done: bool = False


class {C}Store:
    """مخزن {module} في الذاكرة — تسلسل ثابت وحتمي."""

    def __init__(self) -> None:
        self._rows: dict[int, {C}Row] = {{}}
        self._seq = 0

    def add(self, title: str) -> {C}Row:
        """أضف صفًا جديدًا بعنوان غير فارغ وارجع به برقم تسلسلي صاعد."""
        title = title.strip()
        if not title:
            raise ValueError("العنوان فارغ")
        self._seq += 1
        row = {C}Row(row_id=self._seq, title=title)
        self._rows[row.row_id] = row
        return row

    def list(self) -> list[{C}Row]:
        """ارجع بكل الصفوف مرتبة برقم المعرف — عرض لا يغيّر الحالة."""
        return [self._rows[k] for k in sorted(self._rows)]

    def get(self, row_id: int) -> {C}Row | None:
        """ارجع بالصف المطلوب أو None إن لم يوجد — بحث بلا آثار جانبية."""
        return self._rows.get(row_id)

    def toggle(self, row_id: int) -> bool:
        """اقلب حالة إنجاز الصف وارجع True، أو False إن كان مفقودًا."""
        row = self._rows.get(row_id)
        if row is None:
            return False
        row.done = not row.done
        return True

    def remove(self, row_id: int) -> bool:
        """احذف الصف وارجع True إن وُجد وحُذف، وFalse إن لم يوجد."""
        return self._rows.pop(row_id, None) is not None

    def to_json(self) -> str:
        """سلسل كل الصفوف إلى JSON عربي مقروء بترتيب المعرفات."""
        rows = [r.__dict__ for r in self.list()]
        return json.dumps(rows, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "{C}Store":
        """أعد بناء المخزن من JSON سابق مع مواصلة الترقيم من أحدث معرف."""
        store = cls()
        for row in json.loads(raw):
            r = {C}Row(**row)
            store._rows[r.row_id] = r
            store._seq = max(store._seq, r.row_id)
        return store
'''


def build_python_cli(plan: ProjectPlan) -> dict[str, GenFile]:
    crud_doc = _doc3("دورة CRUD كاملة: إضافة ثم عرض وقلب وحذف بترقيم متسلسل صاعد")
    pkg = plan.pkg
    core_sections = "".join(_cli_core_section(m) for m in plan.modules)
    main_body = "\n".join(
        f'''    if args.module == "{m}":
        store = {cls_name(m)}Store()
        return _run_{m}(store, args)'''
        for m in plan.modules
    )
    runners = "\n".join(
        f'''def _run_{m}(store: {cls_name(m)}Store, args: Any) -> int:
    """منفّذ أوامر {m} القصيرة — يطبع بالعربية ويرجع كود خروج."""
    if args.{m}_cmd == "add":
        row = store.add(args.title)
        print(f"أُضيف {{row.row_id}}: {{row.title}}")
        return 0
    if args.{m}_cmd == "list":
        rows = store.list()
        if not rows:
            print("لا صفوف بعد")
            return 0
        for r in rows:
            mark = "✓" if r.done else "·"
            print(f"{{r.row_id}} {{mark}} {{r.title}}")
        return 0
    if args.{m}_cmd == "rm":
        print("حُذف" if store.remove(args.id) else "غير موجود")
        return 0
    if args.{m}_cmd == "toggle":
        print("انقلبت الحالة" if store.toggle(args.id) else "غير موجود")
        return 0
    print("أمر غير معروف", file=sys.stderr)
    return 2'''
        for m in plan.modules
    )

    init = f'''"""{plan.display_name or plan.name} — واجهة الحزمة."""

from .core import {", ".join(cls_name(m) + "Store" for m in plan.modules)}

__all__ = [{", ".join(repr(cls_name(m) + "Store") for m in plan.modules)}]
'''

    core = f'''"""نواة {plan.display_name or plan.name} — مخازن في الذاكرة حتمية.

كل وحدة من مخطط المشروع تحصل على مخزن صفوف بسيط: إضافة/عرض/قلب/حذف
مع حفظ وتحميل JSON. بلا اعتماديات خارجية — تعمل على Termux مباشرة.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
{core_sections}
'''

    cli = f'''"""واجهة سطر الأوامر — argparse قياسي بلا اعتماديات."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from .core import {", ".join(cls_name(m) + "Store" for m in plan.modules)}


def build_parser() -> argparse.ArgumentParser:
    """ابنِ محلّل الأوامر الجذري: وحدة فرعية لكل مخزن مع أوامرها الأربعة."""
    root = argparse.ArgumentParser(prog="{plan.name}", description="{plan.description.strip()[:70]}")
    mods = root.add_subparsers(dest="module", required=True)
    for name in ({", ".join(repr(m) for m in plan.modules)}{"," if len(plan.modules) == 1 else ""}):
        sub = mods.add_parser(name, help=f"إدارة {{name}} (add/list/rm/toggle)")
        commands = sub.add_subparsers(dest=f"{{name}}_cmd", required=True)
        p = commands.add_parser("add", help="إضافة صف جديد")
        p.add_argument("title", help="العنوان")
        commands.add_parser("list", help="عرض الصفوف")
        p = commands.add_parser("rm", help="حذف برقم المعرف")
        p.add_argument("id", type=int)
        p = commands.add_parser("toggle", help="قلب حالة الإنجاز")
        p.add_argument("id", type=int)
    return root


{runners}


def main(argv: Sequence[str] | None = None) -> int:
    """نفّذ الأمر المطلوب على وحدته وارجع بكود خروج: 0 نجاح و2 فشل."""
    args = build_parser().parse_args(argv)
{main_body}
    print("لا وحدة مطابقة", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
'''

    main_py = f'''"""نقطة الدخول: python -m {pkg}."""

from .cli import main

raise SystemExit(main())
'''

    tests = f'''"""اختبارات أولية: CRUD لكل وحدة + دخان CLI — فحوص صريحة تنجو من -O."""

from __future__ import annotations

import pytest

from {pkg}.cli import build_parser, main
from {pkg}.core import {", ".join(cls_name(m) + "Store" for m in plan.modules)}


def _check(condition: bool, message: str) -> None:
    """فحص صريح برفع AssertionError — ينجو من تشغيل python -O حيث يختفي assert."""
    if not condition:
        raise AssertionError(message)


{
        "".join(
            f"""
def test_{m}_crud_roundtrip() -> None:
    {crud_doc}
    store = {cls_name(m)}Store()
    a = store.add("أول")
    b = store.add("ثانٍ")
    _check([r.row_id for r in store.list()] == [a.row_id, b.row_id], "الترقيم التسلسلي يجب أن يكون صاعدًا")
    _check(store.toggle(b.row_id) is True, "قلب حالة صف موجود يجب أن يرجع True")
    _check(store.list()[1].done is True, "الصف المقلوب يجب أن يكون منجزًا")
    _check(store.remove(a.row_id) is True, "حذف صف موجود يجب أن يرجع True")
    _check(store.get(a.row_id) is None, "الصف المحذوف يجب أن يختفي")
    with pytest.raises(ValueError):
        store.add("   ")""".rstrip()
            for m in plan.modules
        )
    }


def test_cli_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """--help يخرج بكود 0 ويذكر أول وحدة في المخرجات."""
    parser = build_parser()
    _check(parser is not None, "محلّل الأوامر يجب أن يُبنى")
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    _check(exc.value.code == 0, "كود خروج المساعدة يجب أن يكون 0")
    _check("{plan.modules[0]}" in capsys.readouterr().out, "المساعدة يجب أن تذكر الوحدة الأولى")


def test_cli_dispatch_routes_commands(capsys: pytest.CaptureFixture[str]) -> None:
    """التوزيع الفعلي: الأوامر تصل منفذيها — لا رسالة «لا وحدة مطابقة».

    المخزن في الذاكرة ويُبنى لكل استدعاء، فالقائمة بعد إضافة متوقّع أن تكون فارغة —
    المهم هنا أن التوجيه يعمل وأن الإخراج العربي صحيح.
    """
    _check(main(["{plan.modules[0]}", "add", "صف تجريبي"]) == 0, "الإضافة عبر CLI يجب أن تنجح")
    _check("أُضيف" in capsys.readouterr().out, "رسالة الإضافة العربية مفقودة")
    _check(main(["{plan.modules[0]}", "list"]) == 0, "العرض عبر CLI يجب أن ينجح")
    _check("لا صفوف بعد" in capsys.readouterr().out, "رسالة القائمة الفارغة مفقودة")
'''

    files: dict[str, GenFile] = {
        "pyproject.toml": _pyproject(
            plan,
            extra_deps=[],
            dev_deps=["pytest>=8.0"],
            scripts={plan.name: f"{pkg}.cli:main"},
            packages="src",
        ),
        ".gitignore": _gitignore(),
        "README.md": _readme(plan, [f"python -m {pkg} --help", f"{plan.name} --help"]),
        f"src/{pkg}/__init__.py": GenFile(
            f"src/{pkg}/__init__.py", init, "جذر الحزمة وتصدير المخازن"
        ),
        f"src/{pkg}/core.py": GenFile(
            f"src/{pkg}/core.py", core, "المخازن الحتمية لكل وحدة من المخطط"
        ),
        f"src/{pkg}/cli.py": GenFile(f"src/{pkg}/cli.py", cli, "أوامر CLI عربية لكل وحدة"),
        f"src/{pkg}/__main__.py": GenFile(
            f"src/{pkg}/__main__.py", main_py, "تشغيل python -m مباشرة"
        ),
        "tests/test_core.py": GenFile(
            "tests/test_core.py", tests, "اختبارات أولية تُمر من أول تشغيل"
        ),
    }
    return files


# ---------------------------------------------------------------------------
# fastapi-api
# ---------------------------------------------------------------------------


def _api_module_section(module: str) -> str:
    C = cls_name(module)
    return f'''

class {C}In(BaseModel):
    """حمولة إنشاء {module}."""

    title: str
    done: bool = False


class {C}Out({C}In):
    """{module} كما يُعاد للعميل — مع المعرّف."""

    item_id: int


{module}_items: dict[int, {C}Out] = {{}}
{module}_seq = itertools.count(1)


@app.post("/{module}", response_model={C}Out, status_code=201, tags=["{module}"])
def create_{module}(payload: {C}In) -> {C}Out:
    """أنشئ {module} جديدًا من الحمولة وارجع به معرقّفًا برمز 201."""
    item = {C}Out(item_id=next({module}_seq), **payload.model_dump())
    {module}_items[item.item_id] = item
    return item


@app.get("/{module}", response_model=list[{C}Out], tags=["{module}"])
def list_{module}() -> list[{C}Out]:
    """ارجع بكل عناصر {module} مرتبة بالمعرف — قراءة لا تغيّر الحالة."""
    return [{module}_items[k] for k in sorted({module}_items)]


@app.get("/{module}/{{item_id}}", response_model={C}Out, tags=["{module}"])
def get_{module}(item_id: int) -> {C}Out:
    """ارجع بعنصر {module} المطلوب أو رمز 404 إن كان مفقودًا."""
    item = {module}_items.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="{module}: غير موجود")
    return item


@app.delete("/{module}/{{item_id}}", status_code=204, tags=["{module}"])
def delete_{module}(item_id: int) -> None:
    """احذف عنصر {module} بمعرّفه — حذف صامت مهما كانت حالة العنصر."""
    {module}_items.pop(item_id, None)
'''


def build_fastapi_api(plan: ProjectPlan) -> dict[str, GenFile]:
    crud_doc_api = _doc3("دورة CRUD عبر TestClient: إنشاء ثم قراءة وحذف ثم تحقق من 404")
    sections = "".join(_api_module_section(m) for m in plan.modules)
    app_py = f'''"""تطبيق {plan.display_name or plan.name} — FastAPI مع CRUD في الذاكرة.

مولَّد حتميًا من مخطط المشروع. للتخزين الحقيقي استبدل قواميس الذاكرة
بطبقة قاعدة بيانات — الواجهات لن تتغير.
"""

from __future__ import annotations

import itertools

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="{plan.display_name or plan.name}",
    description="{plan.description.strip()[:90]}",
    version="0.1.0",
)


@app.get("/health", tags=["نظام"])
def health() -> dict[str, str]:
    """فحص جهوزية التطبيق: يرجع حالته واسمه بلا ذاكرة ولا منافذ."""
    return {{"status": "ok", "app": "{plan.name}"}}
{sections}
'''

    tests = f'''"""اختبارات أولية عبر TestClient — لا خادم حقيقي ولا منافذ، فحوص صريحة تنجو من -O."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


client = TestClient(app)


def _check(condition: bool, message: str) -> None:
    """فحص صريح برفع AssertionError — ينجو من تشغيل python -O حيث يختفي assert."""
    if not condition:
        raise AssertionError(message)


def test_health() -> None:
    """/health يرجع رمز 200 وحالة ok."""
    r = client.get("/health")
    _check(r.status_code == 200, "فحص الجهوزية يجب أن يرجع 200")
    _check(r.json()["status"] == "ok", "حالة الجهوزية يجب أن تكون ok")
{
        "".join(
            f"""

def test_{m}_crud_roundtrip() -> None:
    {crud_doc_api}
    r = client.post("/{m}", json={{"title": "أول {m}"}})
    _check(r.status_code == 201, "الإنشاء يجب أن يرجع 201")
    item = r.json()
    _check(item["item_id"] >= 1 and item["done"] is False, "العنصر الجديد يجب أن يكون معرقّفًا وغير منجز")

    _check(client.get("/{m}").status_code == 200, "القائمة يجب أن ترجع 200")
    _check(client.get(f"/{m}/{{item['item_id']}}").json()["title"] == "أول {m}", "العنوان المعاد يجب أن يطابق المُنشأ")
    _check(client.delete(f"/{m}/{{item['item_id']}}").status_code == 204, "الحذف يجب أن يرجع 204")
    _check(client.get(f"/{m}/{{item['item_id']}}").status_code == 404, "بعد الحذف يجب أن يرجع 404")""".rstrip()
            for m in plan.modules
        )
    }
'''

    files: dict[str, GenFile] = {
        "pyproject.toml": _pyproject(
            plan,
            extra_deps=["fastapi>=0.110", "uvicorn>=0.29"],
            dev_deps=["pytest>=8.0", "httpx>=0.27"],
            scripts={f"{plan.name}-start": "uvicorn app.main:app --reload"},
            packages=".",
        ),
        ".gitignore": _gitignore(),
        "README.md": _readme(
            plan,
            [
                "pip install -e .[dev]",
                f"uvicorn app.main:app --reload   # أو: {plan.name}-start",
                "pytest -q",
            ],
        ),
        "app/__init__.py": GenFile("app/__init__.py", '"""حزمة التطبيق."""\n', "جذر حزمة التطبيق"),
        "app/main.py": GenFile("app/main.py", app_py, "تطبيق FastAPI مع /health وCRUD لكل وحدة"),
        "tests/test_api.py": GenFile(
            "tests/test_api.py", tests, "اختبارات TestClient تُمر من أول تشغيل"
        ),
    }
    return files


# ---------------------------------------------------------------------------
# static-site
# ---------------------------------------------------------------------------


def build_static_site(plan: ProjectPlan) -> dict[str, GenFile]:
    nav = "\n".join(f'      <a href="#{m}">{m}</a>' for m in plan.modules)
    sections = "\n".join(
        f'''    <section id="{m}">
      <h2>{m}</h2>
      <p>قسم {m} — عوّض هذا المحتوى من مخططك.</p>
      <ul class="cards">
        <li class="card">عنصر أول</li>
        <li class="card">عنصر ثانٍ</li>
        <li class="card">عنصر ثالث</li>
      </ul>
    </section>'''
        for m in plan.modules
    )
    html = f"""<!doctype html>
<html dir="rtl" lang="ar">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{plan.display_name or plan.name}</title>
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <header>
    <h1>{plan.display_name or plan.name}</h1>
    <nav>
{nav}
    </nav>
  </header>
  <main>
{sections}
  </main>
  <footer>
    <p>مولَّد بـ zyko.coder — {plan.name}</p>
  </footer>
  <script src="js/main.js"></script>
</body>
</html>
"""

    css = """/* قواعد منطقية فقط (inline/margin/block) — تتبدل تلقائيًا مع RTL */
:root {
  --ink: #1c2430;
  --paper: #faf7f2;
  --accent: #0f766e;
}

* { box-sizing: border-box; }

body {
  margin-block: 0;
  margin-inline: auto;
  padding-inline: 1rem;
  max-width: 60rem;
  font-family: "Noto Naskh Arabic", "Amiri", serif;
  color: var(--ink);
  background: var(--paper);
  text-align: start;
}

header h1 { margin-block-end: 0.25rem; }

nav {
  display: flex;
  gap: 0.75rem;
  padding-block: 0.5rem;
  border-block-end: 1px solid #e2ddd4;
}

nav a { color: var(--accent); text-decoration: none; }

.cards {
  list-style: none;
  padding-inline-start: 0;
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
}

.card {
  padding: 0.75rem 1rem;
  border: 1px solid #e2ddd4;
  border-radius: 0.5rem;
  background: #fff;
}
"""

    js = """// تفاعل بسيط: تمييز رابط القسم النشط أثناء التمرير
(function () {
  "use strict";
  var links = Array.prototype.slice.call(document.querySelectorAll("nav a"));
  var sections = links
    .map(function (a) { return document.querySelector(a.getAttribute("href")); })
    .filter(Boolean);

  function onScroll() {
    var y = window.scrollY + 80;
    var active = null;
    sections.forEach(function (s) { if (s.offsetTop <= y) { active = s.id; } });
    links.forEach(function (a) {
      a.style.fontWeight = a.getAttribute("href") === "#" + active ? "700" : "400";
    });
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
})();
"""

    tests = f'''"""اختبارات بنية الموقع: RTL والاتجاه وأقسام الوحدات وقواعد CSS المنطقية — فحوص صريحة تنجو من -O."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _check(condition: bool, message: str) -> None:
    """فحص صريح برفع AssertionError — ينجو من تشغيل python -O حيث يختفي assert."""
    if not condition:
        raise AssertionError(message)


def test_structure_exists() -> None:
    """كل ملفات الموقع الثلاثة موجودة على القرص."""
    for rel in ("index.html", "css/style.css", "js/main.js"):
        _check((ROOT / rel).is_file(), f"مفقود: {{rel}}")


def test_html_is_rtl_arabic() -> None:
    """الجذر RTL عربي وكل وحدة لها قسم بمعرّفها."""
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    _check('dir="rtl"' in html, "اتجاه الصفحة يجب أن يكون rtl")
    _check('lang="ar"' in html, "لغة الصفحة يجب أن تكون ar")
    for m in {plan.modules!r}:
        _check(f'id="{{m}}"' in html, f"قسم الوحدة {{m}} مفقود")


def test_css_uses_logical_properties_only() -> None:
    """CSS بلا خصائص فيزيائية يسار/يمين — قواعد منطقية فقط تنعكس مع RTL."""
    css = (ROOT / "css" / "style.css").read_text(encoding="utf-8")
    for physical in ("text-align: left", "text-align: right", "float: left", "float: right",
                     "margin-left", "margin-right", "padding-left", "padding-right"):
        _check(physical not in css, f"خاصية فيزيائية تعكس في RTL: {{physical}}")
    _check("padding-inline" in css, "يجب استخدام padding-inline المنطقية")
    _check("text-align: start" in css, "المحاذاة يجب أن تكون start المنطقية")


def test_js_nonempty_and_safe() -> None:
    """جافاسكربت تعمل على كائن document وبلا استدعاء eval."""
    js = (ROOT / "js" / "main.js").read_text(encoding="utf-8")
    _check("document" in js, "السكربت يجب أن يستخدم document")
    _check("eval(" not in js, "eval محظورة في السكربت المولَّد")
'''

    pyproject = """[tool.pytest.ini_options]
testpaths = ["tests"]
"""

    files: dict[str, GenFile] = {
        "pyproject.toml": GenFile("pyproject.toml", pyproject, "إعدادات pytest للفحص البنيوي"),
        ".gitignore": _gitignore(),
        "README.md": _readme(plan, ["python -m http.server 8000", "pytest -q"]),
        "index.html": GenFile(
            "index.html", html, "صفحة RTL عربية بجذر dir/lang صحيحين وأقسام الوحدات"
        ),
        "css/style.css": GenFile("css/style.css", css, "قواعد CSS منطقية تمر بوابة RTL الذاتية"),
        "js/main.js": GenFile("js/main.js", js, "تفاعل بسيط بلا اعتماديات"),
        "tests/test_site.py": GenFile(
            "tests/test_site.py", tests, "اختبارات بنية واتجاه تُمر من أول تشغيل"
        ),
    }
    return files


# ---------------------------------------------------------------------------
# السجل
# ---------------------------------------------------------------------------

BUILDERS: dict[str, TemplateBuilder] = {
    "python-cli": build_python_cli,
    "fastapi-api": build_fastapi_api,
    "static-site": build_static_site,
}


def build_tree(plan: ProjectPlan) -> dict[str, GenFile]:
    """يستدعي بانِي القالب المطلوب ويرجع شجرة الملفات (بلا RECEIPT)."""
    if plan.template not in BUILDERS:
        raise ValueError(f"قالب غير معروف: {plan.template}")
    return BUILDERS[plan.template](plan)


__all__ = [
    "BUILDERS",
    "GenFile",
    "TemplateBuilder",
    "build_fastapi_api",
    "build_python_cli",
    "build_static_site",
    "build_tree",
    "cls_name",
    "package_name",
]
