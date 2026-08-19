#!/bin/sh
set -e

cd /app

echo "Waiting for PostgreSQL..."
until python manage.py shell -c "from django.db import connection; connection.ensure_connection()" >/dev/null 2>&1; do
  sleep 1
done

echo "Applying migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Ensuring B2B direction and metrics..."
python manage.py shell -c "from apps.analytics.services import ensure_b2b_integrity; ensure_b2b_integrity()"

echo "Starting gunicorn..."
exec gunicorn config.wsgi:application \
  --chdir /app/backend \
  --bind 0.0.0.0:8000 \
  --timeout 180 \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  --log-level info


