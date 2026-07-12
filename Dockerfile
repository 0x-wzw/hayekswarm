FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY hayekmas/ hayekmas/
COPY swarm/ swarm/
COPY server/ server/
COPY voidtether/ voidtether/

RUN pip install --no-cache-dir -e ".[server]"

EXPOSE 8000

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
