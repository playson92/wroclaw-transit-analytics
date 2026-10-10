FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml constraints.txt ./
# Resolve the same declared dependencies once; UI/docs changes reuse this layer.
RUN python -c "import subprocess,sys,tomllib; p=tomllib.load(open('pyproject.toml','rb')); subprocess.run([sys.executable,'-m','pip','install','--no-cache-dir','-c','constraints.txt',*p['project']['dependencies'],*p['project']['optional-dependencies']['dashboard'],*p['build-system']['requires']],check=True)"
COPY README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir --no-deps --no-build-isolation '.[dashboard]' \
    && groupadd --gid 10001 wta \
    && useradd --uid 10001 --gid wta --no-create-home wta \
    && mkdir /work \
    && chown wta:wta /work
COPY scripts/compose_smoke.py ./scripts/compose_smoke.py
COPY scripts/real_feed_smoke.py ./scripts/real_feed_smoke.py
COPY scripts/browser_fixtures.py ./scripts/browser_fixtures.py
COPY scripts/portfolio_verify.py ./scripts/portfolio_verify.py
USER 10001:10001
WORKDIR /work
CMD ["python", "-m", "wroclaw_transit_analytics", "--help"]
