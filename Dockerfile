FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data
EXPOSE 9091
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD curl -f http://localhost:9091/health || exit 1
CMD ["python", "-m", "reactor.main"]
