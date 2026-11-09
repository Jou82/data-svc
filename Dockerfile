FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONPATH=/app
# Sem isto o stdout do Python é block-buffered fora de TTY: os print() ficam
# presos num buffer de ~8KB e só aparecem quando ele enche — ou somem no
# SIGTERM do deploy. Foi o que aconteceu em 2026-08-17: o log do container em
# PRD não tinha NENHUMA linha [rag] apesar do endpoint estar respondendo 200,
# o que parecia "código não deployado" e era só buffer.
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# workers=1: cache.py usa TTLCache em memória por processo (não compartilhado).
# Com 2+ workers, um POST invalida só o cache do worker que o atendeu — o outro
# segue servindo GET stale até o TTL expirar (bug confirmado: memoria/usuario/
# saldo servindo dado de até 60-300s atrás mesmo após write bem-sucedido).
# VPS é 1 vCPU (KVM1) — 2 workers já não davam paralelismo real, só esse bug.
CMD ["gunicorn", "--workers=1", "--timeout=120", \
     "--access-logfile=-", "--access-logformat=%(h)s \"%(r)s\" %(s)s %(D)sus", \
     "--bind=0.0.0.0:8000", "src.app:create_app()"]
