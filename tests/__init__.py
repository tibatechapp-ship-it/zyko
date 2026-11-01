# ZYKO test package.
#
# Making `tests` a regular package guarantees `from tests.fakes import ...`
# works under every invocation style (`pytest`, `python -m pytest`,
# `python -m unittest`) on every platform, including Windows runners where
# sys.path handling differs.
