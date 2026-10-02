FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY supportflow ./supportflow
COPY scripts ./scripts
RUN pip install --no-cache-dir . && useradd --create-home appuser && mkdir -p /app/runtime && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["python", "scripts/run_demo.py"]
