FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only necessary files
COPY app/ ./app/
COPY config.ini* ./
COPY docker-compose.yml ./

# Create directories for data persistence
RUN mkdir -p workdir logs downloads

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "-m", "app"]
