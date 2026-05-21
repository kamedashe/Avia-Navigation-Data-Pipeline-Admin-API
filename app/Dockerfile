# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /code

# Copy the current directory contents into the container at /app
COPY . .

# Install system dependencies (rsync/ssh for sync, g++/libgdal for geopandas)
RUN apt-get update && \
    apt-get install -y rsync openssh-client g++ libgdal-dev && \
    rm -rf /var/lib/apt/lists/*

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port the app runs on
EXPOSE 5045

# Run the application
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:5045", "app.main:app"]
