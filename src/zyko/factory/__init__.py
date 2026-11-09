"""zyko.factory — المصنع الموحد: بوابة واحدة فوق محركات البرمجة الحتمية.

المرحلة 7 من خطة الـ90 يوماً: الوحدات (المولّد، المُصلِح، الحلقة،
المحرك على المجلدات القائمة) كانت مكتملة كلٌّ خلف بابها؛ هذه الحزمة
تجعلها **آلة واحدة**: بوابة ``zyko factory`` بلا انحراف سلوك (تفويض
حرفي لمعالجات الوحدات)، بوابات مجمعة في أمر واحد، ولوحة HTML عربية
بلا جافاسكربت تُفتح على الهاتف.

وفوق هذا المصنع يُجمَّع لاحقًا ``zyko AI`` — طبقة الذكاء تركب على آلة
حتمية قابلة للتحقق: كل نداء ذكاء يمر على بواباتٍ تُحكم بالأرقام.
"""

from __future__ import annotations

from zyko.factory.gates import combined_gates_text, run_all_gates
from zyko.factory.map import factory_map_text
from zyko.factory.report_html import (
    fixer_results_html,
    pipeline_result_html,
    workspace_result_html,
)

__all__ = [
    "combined_gates_text",
    "factory_map_text",
    "fixer_results_html",
    "pipeline_result_html",
    "run_all_gates",
    "workspace_result_html",
]
