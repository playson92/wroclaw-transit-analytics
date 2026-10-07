FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md constraints.txt ./
COPY src ./src
RUN python -m pip install --no-cache-dir -c constraints.txt '.[dashboard]' \
    && groupadd --gid 10001 wta \
    && useradd --uid 10001 --gid wta --no-create-home wta \
    && mkdir /work \
    && chown wta:wta /work
COPY scripts/compose_smoke.py ./scripts/compose_smoke.py
COPY scripts/real_feed_smoke.py ./scripts/real_feed_smoke.py
USER 10001:10001
WORKDIR /work
CMD ["python", "-m", "wroclaw_transit_analytics", "--help"]
