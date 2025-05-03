FROM python:3.9-slim-buster

WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend .

WORKDIR /app

COPY frontend .

CMD ["gunicorn", "--workers", "3", "--threads", "2", "--timeout", "0", "backend.main:app", "-b", "0.0.0.0:8080"]