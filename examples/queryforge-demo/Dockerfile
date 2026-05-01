# Build context: QueryForge repository root (see docker-compose build.context)
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /src
COPY . /src/
WORKDIR /src/examples/queryforge-demo
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
