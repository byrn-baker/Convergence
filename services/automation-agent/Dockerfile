FROM python:3.12-slim

WORKDIR /app

# git binary needed by gitpython for the GAIT audit trail
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1

# Configure git identity for audit commits (overridable via env)
RUN git config --global user.email "autoagent@convergence.local" && \
    git config --global user.name "Convergence AutoAgent" && \
    git config --global init.defaultBranch main

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
