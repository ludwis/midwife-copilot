FROM python:3.12-slim

# Install system deps required by spaCy and google-cloud libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies before copying source so this layer is cached
# The spaCy model (xx_ent_wiki_sm) is included as a wheel URL in requirements.txt
# so no separate `python -m spacy download` step is needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Cloud Run expects the container to listen on $PORT (default 8080)
ENV PORT=8080

EXPOSE 8080

# Use 1 worker per container — Cloud Run scales horizontally via instances.
# Long-running requests (Gemini extraction) are not killed by uvicorn by default;
# request duration is governed by Cloud Run --timeout=3600 at the service level.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75"]
