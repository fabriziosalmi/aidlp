FROM python:3.9

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_core_web_lg

COPY . .

# Expose proxy port
EXPOSE 8080

# Default command
CMD ["python", "src/cli.py", "start"]
