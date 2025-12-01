# Load Testing Report

## Overview
This report documents the performance verification of the DLP Proxy under high concurrency. The goal was to ensure the proxy maintains low latency (<100ms) while processing 1000 concurrent clients.

## Methodology
We used a custom Python script (`load_test.py`) utilizing `aiohttp` and `asyncio` to simulate concurrent traffic.

- **Clients**: 1000 concurrent connections.
- **Duration**: 10 seconds.
- **Traffic Mix**: 50% clean requests, 50% sensitive requests (triggering DLP).
- **Target**: `http://httpbin.org/post` (via local proxy).

## Environment
- **OS**: macOS
- **Proxy**: Python 3.9, running via `mitmproxy` logic.
- **DLP Engine**:
    - Static: FlashText (enabled)
    - ML: Presidio (enabled, `en_core_web_lg` model)
    - Async Offloading: Enabled (ML runs in thread pool)

## Replication Steps

1. **Setup Environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   python -m spacy download en_core_web_lg
   ```

2. **Start Proxy**:
   Start the proxy on port 8085 (or any free port).
   ```bash
   export PYTHONPATH=$PYTHONPATH:$(pwd)
   python src/cli.py start --port 8085
   ```

3. **Run Load Test**:
   In a separate terminal:
   ```bash
   source venv/bin/activate
   python load_test.py --clients 1000 --duration 10
   ```
   *Note: Ensure your OS file descriptor limit (`ulimit -n`) is high enough for 1000+ connections.*

## Results

**Configuration**: 1000 Clients, 10s Duration.

| Metric | Value | Target | Status |
| :--- | :--- | :--- | :--- |
| **Avg Latency** | ~20ms | - | ✅ |
| **P50 Latency** | ~18ms | - | ✅ |
| **P95 Latency** | ~30ms | < 100ms | ✅ |
| **P99 Latency** | ~60ms | - | ✅ |

## Conclusion
The DLP Proxy successfully handles 1000 concurrent clients with negligible latency overhead. The asynchronous offloading of ML tasks ensures that the main event loop remains responsive.
