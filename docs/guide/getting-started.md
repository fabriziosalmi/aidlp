# Getting Started

## Prerequisites

- Python 3.9+
- Docker (optional)

## Installation

### Local

```bash
git clone https://github.com/fabriziosalmi/aidlp.git
cd aidlp
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_lg
python src/cli.py start
```

### Docker

```bash
docker-compose up --build -d
```
