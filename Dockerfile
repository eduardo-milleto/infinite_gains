FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/
COPY src /app/src
RUN pip install --no-cache-dir .

COPY . /app
RUN useradd --create-home --shell /bin/bash botuser && chown -R botuser:botuser /app

USER botuser

CMD ["python", "-m", "src.services.trader.__main__"]
