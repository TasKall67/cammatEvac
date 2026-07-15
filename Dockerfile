FROM python:3.12-slim

# System-installed Chromium pulls in its own correct runtime dependencies via
# apt's dependency resolver -- far more reliable than hand-listing individual
# shared libraries. kaleido/choreographer auto-detect it on PATH (checks for
# a "chromium" binary), no extra app-side configuration needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8050
EXPOSE 8050

CMD gunicorn app:server --bind 0.0.0.0:$PORT
