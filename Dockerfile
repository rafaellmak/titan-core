# Stage 1: Build
FROM python:3.11-slim as builder

WORKDIR /app
COPY . .
RUN pip install --user --no-cache-dir .

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .

ENV PATH=/root/.local/bin:$PATH

# Instalar dependências de sistema para DTS e Hardware
RUN apt-get update && apt-get install -y --no-install-recommends \
    device-tree-compiler \
    && rm -rf /var/lib/apt/lists/*

# Rodar como usuário não-root por segurança
RUN useradd -m titan
USER titan

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "titan.daemon:app", "--host", "0.0.0.0", "--port", "8000"]
