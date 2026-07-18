FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=7777
ENV DEMO_MODE=1
ENV PUBLIC_BASE_URL=http://localhost:7777

EXPOSE 7777
# 用 sh -c 確保 Railway 注入的 $PORT 會生效（否則 healthcheck 常失敗）
CMD ["sh", "-c", "gunicorn \"app:app\" --bind 0.0.0.0:${PORT:-7777} --workers 1 --threads 4 --timeout 120"]
