# Single image used by both the dashboard and the paper trading engine.
# CMD is intentionally omitted here and defined per-service in docker-compose.yml.

FROM python:3.12-slim

WORKDIR /app

# Install dependencies before copying the rest of the source so that this
# layer is cached as long as requirements.txt does not change.
COPY trd_auto/requirements.txt trd_auto/requirements.txt
RUN pip install --no-cache-dir -r trd_auto/requirements.txt

# Copy the full project.
COPY . .

# Run as a non-root user to limit the blast radius of a container escape.
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser
