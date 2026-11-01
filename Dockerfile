# ZYKO gateway image — stdlib-only runtime, nothing compiles.
#
#   docker build -t zyko:latest .
#   docker run --rm -p 8787:8787 zyko:latest
#   # with a real provider key:
#   docker run --rm -p 8787:8787 -e OPENAI_API_KEY=sk-... zyko:latest
#   # one-off CLI use:
#   docker run --rm zyko:latest ask "hello" --demo
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# Expose the OpenAI-compatible gateway (see `zyko serve --help`).
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=2).status==200 else 1)"

# Default: run the gateway reachable from outside the container.
ENTRYPOINT ["zyko"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8787"]
