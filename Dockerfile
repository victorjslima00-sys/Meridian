FROM python:3.11-slim

# Evita que o Python escreva arquivos .pyc no disco e forca logs em tempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Configura Timezone para horario de Brasilia (Crucial para a B3)
ENV TZ=America/Sao_Paulo
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Instala dependencias do sistema necessarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    sqlite3 \
    cron \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Configura o diretorio de trabalho
WORKDIR /app

# Copia os requirements e instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o codigo fonte
COPY . .

# Cria os diretorios de dados persistentes caso nao existam
RUN mkdir -p /app/data /app/logs

# Legacy cron order writer disabled (NEXUS-004: single paper execution authority).
# Default Meridian runtime exposes exactly ONE Paper order authority: the modern typed path in backend.app.main.
# The legacy scripts/fase2_paper_trading.py is preserved as reference/historical code only.

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

