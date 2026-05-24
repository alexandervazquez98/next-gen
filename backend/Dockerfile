FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# Install OS tools used by health checks and backups.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

COPY engines /app/engines
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
