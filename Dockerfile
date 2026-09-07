# Build stage
FROM python:3.12-slim as builder

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
FROM python:3.12-slim

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
