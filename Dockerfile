FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir . \
    && groupadd --gid 10001 wta \
    && useradd --uid 10001 --gid wta --no-create-home wta \
    && mkdir /work \
    && chown wta:wta /work
COPY scripts/compose_smoke.py ./scripts/compose_smoke.py
USER 10001:10001
WORKDIR /work
CMD ["python", "-m", "wroclaw_transit_analytics", "--help"]
