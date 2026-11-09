# عيّنة workspace — أداة صغيرة قائمة

مجلد قائم فيه ما يُصلَح آليًا وما يبقى يدويًا، لتجربة المرحلة 5:

```bash
python -m zyko.workspace run --src samples/workspace/small_tool
python -m zyko.workspace run --src samples/workspace/small_tool --format json
```

- `tool.py` — عمدًا: except عام، مقارنة بلا None، لامدا، open بلا with
- `secure.py` — عمدًا: md5 بدل sha256
- `clean_util.py` — نظيف تمامًا: يجب أن يبقى بلا أي تغيير (الاعتدال)

الافتراضي تجربة جافة لا تكتب شيئًا. للنسخة المُصلَحة:
`--out مجلد-جديد`، وللتعديل الموضعي: `--in-place --yes`.
