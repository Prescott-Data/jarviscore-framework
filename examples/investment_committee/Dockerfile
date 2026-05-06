FROM python:3.12-slim

WORKDIR /app

# Install dependencies + supervisor
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt supervisor

# Copy application code
COPY agents/       agents/
COPY templates/    templates/
COPY static/       static/
COPY dashboard.py  .
COPY committee.py  .
COPY portfolio.json .
COPY supervisord.conf .

# Persistent data directories (overridden by volumes in compose)
RUN mkdir -p /app/data/memos /app/blob_storage /app/logs

EXPOSE 8004

CMD ["supervisord", "-c", "supervisord.conf"]
