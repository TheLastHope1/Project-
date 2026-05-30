FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY polymarket_scanner/ polymarket_scanner/
COPY scanner.env.example scanner.env.example

EXPOSE 8787

CMD ["python", "-m", "polymarket_scanner.web", "--host", "0.0.0.0"]
