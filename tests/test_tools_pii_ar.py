"""اختبارات zyko.tools.pii_ar — الأداة الحتمية للخصوصية العربية (D1–2 + D5)."""

import json

from zyko.tools.pii_ar import (
    TYPE_LABELS,
    PIIScanner,
    normalize_digits,
    redact,
    scan,
    to_arabic_digits,
    to_western_digits,
)

# ------------------------------------------------------------ تطبيع الأرقام


def test_normalize_length_preserving():
    assert normalize_digits("٠٥٠١٢٣٤٥٦٧") == "0501234567"
    assert normalize_digits("0501234567") == "0501234567"
    assert len(normalize_digits("١٢٣-٤٥٦")) == len("١٢٣-٤٥٦")


def test_to_western_and_arabic():
    assert to_western_digits("١٢٣") == "123"
    assert to_arabic_digits("123") == "١٢٣"


# ------------------------------------------------------------ الهواتف


def test_sa_phone_local():
    assert any(f.type == "phone" and f.valid for f in scan("اتصل 0501234567 اليوم"))


def test_eg_phone():
    assert any(f.type == "phone" for f in scan("الرقم 01012345678 متاح"))


def test_phone_arabic_indic_digits():
    fs = scan("جوال التاجر ٠٥٠١٢٣٤٥٦٧ هنا")
    assert any(f.type == "phone" and f.valid for f in fs)
    # القيمة تُعرض بالأرقام العربية كما وردت
    phone = next(f for f in fs if f.type == "phone")
    assert any(ord(c) >= 0x0660 and ord(c) <= 0x0669 for c in phone.value)


def test_phone_intl_format():
    assert any(f.type == "phone" for f in scan("اتصل +966112345678 مباشرة"))


def test_luhn_like_number_not_phone():
    # سلسلة رقمية طويلة بلا سياق هاتف لا تُبلَّغ هاتفًا إن كانت بطاقة صالحة
    fs = scan("بطاقة 4532015112830366 صالحة")
    assert fs and fs[0].type == "bank_card"


# ------------------------------------------------------------ الهويات الوطنية


def test_sa_national_id_valid_prefix():
    assert any(
        f.type == "national_id" and f.country == "SA" and f.valid
        for f in scan("الهوية 1012345670 مسجلة")
    )


def test_eg_national_id_date_checked():
    # تاريخ صحيح 1900-01-01 → مئوية 2
    assert any(f.type == "national_id" and f.valid for f in scan("القومي 29001011234567 وصل"))
    # شهر 13 مستحيل → غير صالح لكنه يبقى مكتشفًا
    fs = [f for f in scan("القومي 29013111234567 وصل") if f.type == "national_id"]
    assert fs and fs[0].valid is False


def test_ae_national_id_15_digits():
    assert any(
        f.type == "national_id" and f.country == "AE" for f in scan("هوية 784199012345678 سارية")
    )


# ------------------------------------------------------------ آيبان وبطاقات


def test_iban_mod97_valid():
    assert any(f.type == "iban" and f.valid for f in scan("الآيبان SA0380000000608010167519 صحيح"))


def test_iban_mod97_invalid_rejected():
    # تعديل رقم التحقق يُسقط الآيبان كليًا — لا يمر أبدًا كملاحظة صالحة
    fs = [f for f in scan("الآيبان SA0380000000608010167518 صحيح") if f.type == "iban"]
    assert not any(f.valid for f in fs)


def test_visa_card_luhn():
    assert any(f.type == "bank_card" and f.valid for f in scan("بطاقة 4532015112830366 صالحة"))


def test_mada_card_brand():
    from zyko.tools.pii_ar.patterns import card_brand

    assert card_brand("9682000000000006") == "مدى"
    fs = scan("مدى 9682000000000006 تعمل")
    assert any(f.type == "bank_card" and f.valid for f in fs)


# ------------------------------------------------------------ أسماء وعناوين


def test_full_name_detected():
    fs = [f for f in scan("قام محمد أحمد بتسجيل الطلب") if f.type == "person_name"]
    assert fs and len(fs[0].value.split()) >= 2


def test_address_detected():
    assert any(f.type == "address" for f in scan("يقطع في الرياض حي النرجس شارع الأمير سلطان"))


# ------------------------------------------------------------ الحجب


def test_redact_mask_keeps_shape():
    cleaned, findings = redact("اتصل 0501234567", mode="mask")
    assert findings and len(cleaned) == len("اتصل 0501234567")
    assert "0501234567" not in cleaned


def test_redact_placeholder_arabic():
    cleaned, findings = redact("اسمي محمد أحمد ورقمي 0501234567", mode="placeholder")
    assert "[اسم]" in cleaned and "[هاتف]" in cleaned
    assert len(findings) == 2


def test_types_filter():
    fs = scan("محمد أحمد على support@x.example أو 0501234567", types=["email"])
    assert all(f.type == "email" for f in fs)


def test_min_confidence_filter():
    scanner = PIIScanner(min_confidence=0.99)
    assert scanner.scan("محمد أحمد هنا") == [] or all(
        f.confidence >= 0.99 for f in scanner.scan("محمد أحمد هنا")
    )


# ------------------------------------------------------------ البوابة 20/20


def test_phase0_gate_arabic_mix_20_of_20():
    """بوابة المرحلة 0: كل العينات المزروعة تُكتشف دفعة واحدة."""
    from pathlib import Path

    sample = Path(__file__).parents[1] / "samples" / "arabic_mix.txt"
    assert sample.is_file(), "samples/arabic_mix.txt مفقود"
    findings = PIIScanner().scan(sample.read_text(encoding="utf-8"))
    assert len(findings) == 20, f"البوابة: {len(findings)}/20"


def test_type_labels_arabic():
    assert TYPE_LABELS["phone"] == "هاتف"
    assert TYPE_LABELS["iban"] == "آيبان"


# ------------------------------------------------------------ CLI


def _main(argv):
    from zyko.tools.pii_ar.__main__ import main

    return main(argv)


def test_cli_scan_text(capsys):
    assert _main(["scan", "اتصل 0501234567"]) == 1
    out = capsys.readouterr().out
    assert "هاتف" in out and "المجموع" in out


def test_cli_scan_json(capsys):
    _main(["scan", "اتصل 0501234567", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "zyko_pii_ar" and payload["count"] == 1


def test_cli_redact_placeholder(capsys):
    assert _main(["redact", "اسمي محمد أحمد", "--mode", "placeholder"]) == 1
    assert "[اسم]" in capsys.readouterr().out


def test_cli_scan_clean_exit_zero(capsys):
    assert _main(["scan", "نص عادي لا بيانات فيه"]) == 0
