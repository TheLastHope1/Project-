FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml .
COPY polymarket_edge/ polymarket_edge/
COPY src/ src/
COPY polymarket_scanner/ polymarket_scanner/
COPY scanner.env.example scanner.env.example
COPY .env.example .env.example

EXPOSE 8000

CMD ["uvicorn", "polymarket_edge.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
