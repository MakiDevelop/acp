FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
COPY acp/ acp/

RUN pip install --no-cache-dir .

EXPOSE 8700
CMD ["uvicorn", "acp.server:app", "--host", "0.0.0.0", "--port", "8700"]
