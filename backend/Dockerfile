FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "software_developer_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
