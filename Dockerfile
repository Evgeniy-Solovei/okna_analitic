FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY manage.py /app/manage.py
COPY scripts /app/scripts
COPY docker/web.sh /app/docker/web.sh

RUN chmod +x /app/docker/web.sh

EXPOSE 8000

CMD ["/app/docker/web.sh"]
