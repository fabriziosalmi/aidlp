# Build stage.
# Pinned by digest, not the floating 3.12-slim tag: the same commit rebuilt
# weeks apart otherwise picks up a different Debian slim (different glibc /
# openssl patch level, different Python 3.12.x) and produces a different
# artefact from identical source. Bump deliberately.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS builder

WORKDIR /app

RUN rm -rf /var/lib/apt/lists/* && \
    apt-get update && \
    apt-get install -y --no-install-recommends --fix-missing build-essential curl

# Install Poetry from PyPI at a pinned version. The bootstrap script at
# install.python-poetry.org is unversioned and unverified, so every build
# trusted whatever that endpoint happened to serve.
RUN pip install --no-cache-dir "poetry==2.4.3" "poetry-plugin-export==1.10.0"

COPY pyproject.toml poetry.lock ./

# Export WITH hashes and make pip enforce them. Without this, an index or
# MITM serving a different artifact under the same name and version during
# the build would go undetected, even though poetry.lock records the hash.
RUN poetry export -f requirements.txt --output requirements.txt
RUN pip install --no-cache-dir --require-hashes --prefix=/install -r requirements.txt

# Install SpaCy models directly to the prefix (Only SM to avoid 800MB bloat).
# --no-deps: the model pins spacy<3.8 and would otherwise downgrade the
# resolved dependency set behind poetry's back.
# Pinned by digest for the same reason as the hash-checked install above:
# this wheel ships inside the image and was previously fetched unverified.
RUN pip install --no-cache-dir --no-deps --prefix=/install \
    "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl#sha256=1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"

# Final stage
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

# Traceability on every build path, not just the tag-triggered workflow where
# docker/metadata-action adds its own labels. A plain `docker build .` or the
# documented `docker-compose build` produced an image whose `docker inspect`
# named no commit at all. Pass with:
#   --build-arg VCS_REF=$(git rev-parse HEAD) --build-arg VERSION=4.0.1
ARG VCS_REF=unknown
ARG VERSION=unknown
LABEL org.opencontainers.image.title="aidlp" \
      org.opencontainers.image.description="DLP proxy for LLM endpoints" \
      org.opencontainers.image.source="https://github.com/fabriziosalmi/aidlp" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}"

# Install dumb-init for proper signal handling
RUN apt-get update && apt-get install -y --no-install-recommends dumb-init && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create a non-root user
RUN useradd -m appuser && chown -R appuser /app
USER appuser

COPY --chown=appuser:appuser src/ /app/src/

# Expose proxy port
EXPOSE 8080 9090

# Ensure Python can find the src module and binaries
ENV PYTHONPATH="/app"
ENV PATH="/usr/local/bin:$PATH"

# Default command using dumb-init
ENTRYPOINT ["dumb-init", "--"]
CMD ["python", "-m", "src.cli", "start", "--port", "8080"]
