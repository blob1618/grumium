# testing/Dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV TZ="America/Argentina/Buenos_Aires"

WORKDIR /app

# Install dependencies
COPY testing/requirements.txt /app/testing/requirements.txt
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r testing/requirements.txt

# Copy project code
COPY . /app/

EXPOSE 8501

CMD ["streamlit", "run", "testing/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
