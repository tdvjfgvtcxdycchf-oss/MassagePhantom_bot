FROM python:3.11-slim

WORKDIR /app

# Зависимости отдельным слоем — кешируются если requirements не менялся
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
