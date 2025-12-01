# What is AI DLP Proxy?

AI DLP Proxy is a secure gateway designed to sit between your applications and external LLM providers (like OpenAI, Anthropic, or internal models). Its primary purpose is to **prevent sensitive data leakage**.

## Why use it?

Developers often paste secrets, PII, or internal database connection strings into LLM prompts. This proxy intercepts these requests and redacts sensitive information *before* it leaves your network.

## Key Features

- **Hybrid Redaction**: Uses both static lists (FlashText) and ML models (Presidio).
- **SSL Bumping**: Inspects HTTPS traffic.
- **Observability**: Prometheus metrics and JSON logs.
