FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# IMPORTANT: do not pass $PORT on the command line.
# run_server.py reads Railway's PORT environment variable in Python and
# converts it to int before handing it to uvicorn.
CMD ["python", "run_server.py"]
