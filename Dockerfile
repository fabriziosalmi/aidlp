# Build stage
FROM python:3.14-slim as builder

WORKDIR /app

RUN rm -rf /var/lib/apt/lists/* && \
    apt-get update && \
    apt-get install -y --no-install-recommends --fix-missing build-essential curl

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"
RUN poetry self add poetry-plugin-export

COPY pyproject.toml poetry.lock ./

# Install dependencies to a specific prefix
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Install SpaCy models directly to the prefix (Only SM to avoid 800MB bloat)
RUN pip install --no-cache-dir --prefix=/install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl

# Final stage
FROM python:3.14-slim

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
