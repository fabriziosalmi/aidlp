# Redaction Engine

The AI DLP Proxy uses a **Hybrid Redaction Engine** to ensure both high performance and high accuracy when sanitizing sensitive data.

## How it Works

The redaction process happens in two stages for every request body:

### 1. Static Redaction (Fast)
The first layer uses **FlashText**, an algorithm optimized for replacing keywords in a single pass.
- **Purpose**: Detects known secrets (API keys, specific project codenames, internal tokens).
- **Source**: Keywords are loaded from `terms.txt` or HashiCorp Vault.
- **Performance**: Extremely fast (microseconds), independent of the number of keywords.

### 2. Machine Learning Redaction (Smart)
The second layer uses **Microsoft Presidio** (backed by SpaCy `en_core_web_lg`).
- **Purpose**: Detects PII (Personally Identifiable Information) that follows patterns or context, such as:
    - Names
    - Phone Numbers
    - Email Addresses
    - Credit Card Numbers
    - Crypto Wallets
- **Performance**: Slower than static (milliseconds), but runs asynchronously to minimize impact.
- **Configuration**:
    - `ml_enabled`: Can be toggled off for maximum speed.
    - `ml_threshold`: Confidence score (0.0 - 1.0) to filter false positives.

## Flow Diagram

```mermaid
graph LR
    A[Request] --> B{Static Redaction}
    B -->|Found Terms| C[Replace with [REDACTED]]
    B -->|Clean| D{ML Redaction}
    C --> D
    D -->|Found PII| E[Replace with [REDACTED]]
    D -->|Clean| F[Forward to LLM]
    E --> F
```
