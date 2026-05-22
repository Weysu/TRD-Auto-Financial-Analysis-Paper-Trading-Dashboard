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
RUN addgroup --system appgroup && adduser --system --ingroup appgroup --home /home/appuser --create-home appuser

# Give appuser ownership of all files (including paper_trader/) and ensure
# all directories are readable and executable by the owning user.
RUN chown -R appuser:appgroup /app \
 && chmod -R 755 /app

USER appuser

ENV HOME=/home/appuser
ENV YF_CACHE_DIR=/tmp/yfinance-cache
