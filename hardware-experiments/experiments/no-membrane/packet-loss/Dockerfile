FROM python:3.11-slim

# Install NumPy required for heavy coordinate transformation matrix workloads
RUN pip install --no-cache-dir numpy

WORKDIR /app
COPY receiver.py .

# Run with python -u to ensure stdout/stderr are unbuffered for log viewing
CMD ["python", "-u", "receiver.py"]