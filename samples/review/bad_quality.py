"""ملف معيب عمدًا — ضعف الجودة (بوابة المرحلة 2: G1).

هذا الملف يغطي كل قواعد الجودة التسع حتى تبقى البوابة G6 (لا قاعدة ميتة)
صادقة: كل قاعدة في السجل تُطلق فعليًا على واحد من الملفات المعيبة الثلاثة.
الوسوم «P-xx» توضع عند سطر الإرساء الفعلي للقاعدة (سطر التعريف غالبًا).
"""

import os  # P-09 R-QLT-207
import sys


def process(sum):  # P-01 R-QLT-208
    """يجمع المجموع الممرر."""
    total = sum
    return total


make_greeting = lambda name: "مرحبًا " + name  # P-02 R-QLT-209


def compare(value):
    """يقارن القيمة بالعدم بطريقة خاطئة."""
    return value == None  # P-03 R-QLT-206


def decide(x):
    """يتخذ قرارًا بتداخل فروع عميق."""
    if x > 0:
        if x > 1:
            if x > 2:
                if x > 3:
                    if x > 4:  # P-04 R-QLT-202
                        return x
    return 0


def too_many(a, b, c, d, e, f, g, h):  # P-05 R-QLT-203
    """يجمع ثمانية معاملات في عدد واحد."""
    return a + b + c + d + e + f + g + h


def long_runner():  # P-06 R-QLT-201
    """يجري حصيلة طويلة سطرًا بسطر لإظهار الدالة الممتدة."""
    acc = 0
    acc += 1
    acc += 2
    acc += 3
    acc += 4
    acc += 5
    acc += 6
    acc += 7
    acc += 8
    acc += 9
    acc += 10
    acc += 11
    acc += 12
    acc += 13
    acc += 14
    acc += 15
    acc += 16
    acc += 17
    acc += 18
    acc += 19
    acc += 20
    acc += 21
    acc += 22
    acc += 23
    acc += 24
    acc += 25
    acc += 26
    acc += 27
    acc += 28
    acc += 29
    acc += 30
    acc += 31
    acc += 32
    acc += 33
    acc += 34
    acc += 35
    acc += 36
    acc += 37
    acc += 38
    acc += 39
    acc += 40
    acc += 41
    acc += 42
    acc += 43
    acc += 44
    acc += 45
    acc += 46
    acc += 47
    acc += 48
    acc += 49
    acc += 50
    acc += 51
    acc += 52
    return acc


class Report:  # P-07 R-QLT-204
    def build(self, rows):
        """يبني صفوف التقرير كما هي."""
        return rows


def platform_tag():
    """يرجع وسم المنصة الحالية."""
    return sys.platform


def no_hints(text):  # P-08 R-QLT-205
    """ينظف النص من الفراغات الطرفية."""
    return text.strip()
