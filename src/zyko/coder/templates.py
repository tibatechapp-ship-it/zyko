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

    id: int
    title: str
    done: bool = False


class {C}Store:
    """مخزن {module} في الذاكرة — تسلسل ثابت وحتمي."""

    def __init__(self) -> None:
        self._rows: dict[int, {C}Row] = {{}}
        self._seq = 0

    def add(self, title: str) -> {C}Row:
        title = title.strip()
        if not title:
            raise ValueError("العنوان فارغ")
        self._seq += 1
        row = {C}Row(id=self._seq, title=title)
        self._rows[row.id] = row
        return row

    def list(self) -> list[{C}Row]:
        return [self._rows[k] for k in sorted(self._rows)]

    def get(self, row_id: int) -> {C}Row | None:
        return self._rows.get(row_id)

    def toggle(self, row_id: int) -> bool:
        row = self._rows.get(row_id)
        if row is None:
            return False
        row.done = not row.done
        return True

    def remove(self, row_id: int) -> bool:
        return self._rows.pop(row_id, None) is not None

    def to_json(self) -> str:
        rows = [r.__dict__ for r in self.list()]
        return json.dumps(rows, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "{C}Store":
        store = cls()
        for row in json.loads(raw):
            r = {C}Row(**row)
            store._rows[r.id] = r
            store._seq = max(store._seq, r.id)
        return store
'''


def _cli_cli_section(module: str) -> str:
    return f'''    # --- {module} ---
    sub_{module} = mods.add_parser("{module}", help="إدارة {module} (add/list/rm/toggle)")
    {module}_sub = sub_{module}.add_subparsers(dest="{module}_cmd", required=True)
    p = {module}_sub.add_parser("add", help="إضافة صف جديد")
    p.add_argument("title", help="العنوان")
    p = {module}_sub.add_parser("list", help="عرض الصفوف")
    p = {module}_sub.add_parser("rm", help="حذف برقم المعرف")
    p.add_argument("id", type=int)
    p = {module}_sub.add_parser("toggle", help="قلب حالة الإنجاز")
    p.add_argument("id", type=int)
'''


def build_python_cli(plan: ProjectPlan) -> dict[str, GenFile]:
    pkg = plan.pkg
    core_sections = "".join(_cli_core_section(m) for m in plan.modules)
    cli_sections = "".join(_cli_cli_section(m) for m in plan.modules)
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
        print(f"أُضيف {{row.id}}: {{row.title}}")
        return 0
    if args.{m}_cmd == "list":
        rows = store.list()
        if not rows:
            print("لا صفوف بعد")
            return 0
        for r in rows:
            mark = "✓" if r.done else "·"
            print(f"{{r.id}} {{mark}} {{r.title}}")
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
    root = argparse.ArgumentParser(prog="{plan.name}", description="{plan.description.strip()[:70]}")
    mods = root.add_subparsers(dest="module", required=True)
{cli_sections}
    return root


{runners}


def main(argv: Sequence[str] | None = None) -> int:
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

    tests = f'''"""اختبارات أولية: CRUD لكل وحدة + دخان CLI."""

from __future__ import annotations

import pytest

from {pkg}.cli import build_parser, main
from {pkg}.core import {", ".join(cls_name(m) + "Store" for m in plan.modules)}


{
        "".join(
            f"""
def test_{m}_crud_roundtrip() -> None:
    store = {cls_name(m)}Store()
    a = store.add("أول")
    b = store.add("ثانٍ")
    assert [r.id for r in store.list()] == [a.id, b.id]
    assert store.toggle(b.id) is True
    assert store.list()[1].done is True
    assert store.remove(a.id) is True
    assert store.get(a.id) is None
    with pytest.raises(ValueError):
        store.add("   ")
""".rstrip()
            for m in plan.modules
        )
    }


def test_cli_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    assert parser is not None
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "{plan.modules[0]}" in capsys.readouterr().out


def test_cli_dispatch_routes_commands(capsys: pytest.CaptureFixture[str]) -> None:
    """التوزيع الفعلي: الأوامر تصل منفذيها — لا رسالة «لا وحدة مطابقة».

    المخزن في الذاكرة ويُبنى لكل استدعاء، فالقائمة بعد إضافة متوقّع أن تكون فارغة —
    المهم هنا أن التوجيه يعمل وأن الإخراج العربي صحيح.
    """
    assert main(["{plan.modules[0]}", "add", "صف تجريبي"]) == 0
    assert "أُضيف" in capsys.readouterr().out
    assert main(["{plan.modules[0]}", "list"]) == 0
    assert "لا صفوف بعد" in capsys.readouterr().out
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

    id: int


{module}_items: dict[int, {C}Out] = {{}}
{module}_seq = itertools.count(1)


@app.post("/{module}", response_model={C}Out, status_code=201, tags=["{module}"])
def create_{module}(payload: {C}In) -> {C}Out:
    item = {C}Out(id=next({module}_seq), **payload.model_dump())
    {module}_items[item.id] = item
    return item


@app.get("/{module}", response_model=list[{C}Out], tags=["{module}"])
def list_{module}() -> list[{C}Out]:
    return [{module}_items[k] for k in sorted({module}_items)]


@app.get("/{module}/{{item_id}}", response_model={C}Out, tags=["{module}"])
def get_{module}(item_id: int) -> {C}Out:
    item = {module}_items.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="{module}: غير موجود")
    return item


@app.delete("/{module}/{{item_id}}", status_code=204, tags=["{module}"])
def delete_{module}(item_id: int) -> None:
    {module}_items.pop(item_id, None)
'''


def build_fastapi_api(plan: ProjectPlan) -> dict[str, GenFile]:
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
    return {{"status": "ok", "app": "{plan.name}"}}
{sections}
'''

    tests = f'''"""اختبارات أولية عبر TestClient — لا خادم حقيقي ولا منافذ."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
{
        "".join(
            f"""

def test_{m}_crud_roundtrip() -> None:
    r = client.post("/{m}", json={{"title": "أول {m}"}})
    assert r.status_code == 201
    item = r.json()
    assert item["id"] >= 1 and item["done"] is False

    assert client.get("/{m}").status_code == 200
    assert client.get(f"/{m}/{{item['id']}}").json()["title"] == "أول {m}"
    assert client.delete(f"/{m}/{{item['id']}}").status_code == 204
    assert client.get(f"/{m}/{{item['id']}}").status_code == 404
""".rstrip()
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

    tests = f'''"""اختبارات بنية الموقع: RTL والاتجاه وأقسام الوحدات وقواعد CSS المنطقية."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_structure_exists() -> None:
    for rel in ("index.html", "css/style.css", "js/main.js"):
        assert (ROOT / rel).is_file(), f"مفقود: {{rel}}"


def test_html_is_rtl_arabic() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'dir="rtl"' in html
    assert 'lang="ar"' in html
    for m in {plan.modules!r}:
        assert f'id="{{m}}"' in html


def test_css_uses_logical_properties_only() -> None:
    css = (ROOT / "css" / "style.css").read_text(encoding="utf-8")
    for physical in ("text-align: left", "text-align: right", "float: left", "float: right",
                     "margin-left", "margin-right", "padding-left", "padding-right"):
        assert physical not in css, f"خاصية فيزيائية تعكس في RTL: {{physical}}"
    assert "padding-inline" in css
    assert "text-align: start" in css


def test_js_nonempty_and_safe() -> None:
    js = (ROOT / "js" / "main.js").read_text(encoding="utf-8")
    assert "document" in js
    assert "eval(" not in js
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
