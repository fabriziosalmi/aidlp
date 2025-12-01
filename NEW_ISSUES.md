# Feature Requests Draft

Here are the drafts for the 4 requested issues. You can copy and paste these directly into GitHub Issues.

---

## Issue 1: Auto-block Offending Clients with LLM-Native Error Responses

**Title:** feat: Auto-block offending clients and return LLM-friendly error messages

**Description:**
Implement a mechanism to automatically temporarily block clients that repeatedly violate DLP policies (e.g., attempting to leak secrets or PII).

**Key Features:**
1.  **Offending Client Metrics**: Track violations per client IP/API Key.
2.  **Auto-Block**: Temporarily block clients exceeding a violation threshold (e.g., 5 violations in 1 minute).
3.  **LLM-Native Responses**: Instead of a generic 403 HTTP error, return a response in the format expected by the LLM client (e.g., OpenAI JSON error format) containing a clear message: "You have been temporarily blocked for {duration} due to repeated policy violations."

**Rationale:**
Active blocking improves security posture by stopping bad actors or malfunctioning scripts early. Returning errors in the expected JSON format prevents client applications from crashing due to parsing errors when they receive a raw HTML/text response.

---

## Issue 2: Enhanced Observability Metrics for Grafana

**Title:** feat: Expand Prometheus metrics for granular observability

**Description:**
Expand the current Prometheus metrics collector to include more granular data points suitable for detailed Grafana dashboards.

**Proposed Metrics:**
*   `dlp_pii_detected_total{type="EMAIL|SSN|..."}`: Count of specific PII types detected.
*   `proxy_latency_histogram_seconds`: Latency distribution (p95, p99).
*   `proxy_token_usage_total`: estimated input/output token counts (if possible to parse).
*   `proxy_client_errors_total`: 4xx errors broken down by type.
*   `dlp_processing_time_seconds`: Time spent in the DLP engine vs. network overhead.

**Rationale:**
Current metrics provide high-level throughput info but lack the detail needed for security auditing (what *kind* of data is being leaked?) and performance tuning (is DLP slowing us down?).

---

## Issue 3: Dynamic Traffic Control & Config Hot-Reload

**Title:** feat: Dynamic client blocking and Dry-Run mode via config hot-reload

**Description:**
Allow administrators to update the proxy configuration without restarting the service and dropping active connections.

**Key Features:**
1.  **Config Hot-Reload**: Watch `config.yaml` for changes and reload policies on the fly.
2.  **Dynamic Blocking**: Ability to add IPs/CIDRs to a `deny_list` in config and have it take effect immediately.
3.  **Dry-Run Mode**: A global or per-client setting to disable blocking/redaction temporarily (pass-through) for debugging purposes, controllable via config.

**Rationale:**
In a production environment, restarting the proxy to ban an IP or debug a false positive causes downtime. Hot-reloading enables "Day 2" operations and rapid incident response.

---

## Issue 4: System Prompt Injection & Override

**Title:** feat: Global System Prompt Injection for Governance

**Description:**
Implement a feature to inject or override the "System Prompt" in outgoing LLM requests.

**Functionality:**
*   **Injection**: Append a mandatory governance instruction to the existing system prompt (e.g., "Ensure all answers are compliant with Corp Policy X").
*   **Override**: Completely replace the user-provided system prompt with a secure default.
*   **Configurable**: Define the injected prompt in `config.yaml`.

**Rationale:**
This ensures that regardless of what the end-user asks or how the client application is configured, the LLM always receives critical governance instructions (e.g., "Do not generate code with known vulnerabilities", "Tone must be professional").
