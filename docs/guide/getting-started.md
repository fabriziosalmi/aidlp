# Getting Started

## Prerequisites

- Python 3.9+
- Docker (optional)

## Installation

### Local Setup

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/fabriziosalmi/aidlp.git
    cd aidlp
    ```

2.  **Create a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install poetry
    poetry install
    poetry run python -m spacy download en_core_web_lg
    ```

4.  **Start the proxy**:
    ```bash
    poetry run python src/cli.py start
    ```

    The proxy will start on port `8080` (traffic) and `9090` (metrics).

### Docker Setup

1.  **Build and Run**:
    ```bash
    docker-compose up --build -d
    ```

2.  **Verify**:
    ```bash
    curl -x http://localhost:8080 http://httpbin.org/ip
    ```
