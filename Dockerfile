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
# Railway 會注入 $PORT；單 worker 較穩（免費／小方案記憶體較緊）
CMD gunicorn "app:app" --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 120
