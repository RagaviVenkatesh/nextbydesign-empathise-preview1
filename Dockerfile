FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY templates ./templates
CMD ["sh", "-c", "exec uvicorn server_supabase:app --app-dir app --host 0.0.0.0 --port ${PORT:-8080} --no-access-log"]
