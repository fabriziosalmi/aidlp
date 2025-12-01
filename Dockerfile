# Build stage
FROM python:3.12-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential

COPY requirements.txt .
# Install dependencies to a specific prefix
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Install SpaCy models directly to the prefix
# Using direct URL or module download if PYTHONPATH is set.
# Easiest is to use pip install with the wheel URL for the models to ensure they go to /install
RUN pip install --no-cache-dir --prefix=/install https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.7.1/en_core_web_lg-3.7.1-py3-none-any.whl
RUN pip install --no-cache-dir --prefix=/install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl

# Final stage
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create a non-root user
RUN useradd -m appuser && chown -R appuser /app
USER appuser

COPY . .

# Expose proxy port
EXPOSE 8080

# Default command
CMD ["python", "-m", "src.cli", "start"]
