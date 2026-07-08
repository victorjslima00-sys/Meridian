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

# Define o cron job dentro do container para rodar a cada 45 minutos (*/45)
# O cron precisa ler as env vars, entao salvamos as env vars num arquivo pro script ler
RUN echo "*/45 * * * * root cd /app && /usr/local/bin/python scripts/fase2_paper_trading.py >> /var/log/cron.log 2>&1" > /etc/cron.d/bot-cron
RUN chmod 0644 /etc/cron.d/bot-cron
RUN crontab /etc/cron.d/bot-cron
RUN touch /var/log/cron.log

# O Entrypoint garante que as variaveis do docker-compose vao pro crontab
# e inicia o servico do cron em foreground
CMD env > /etc/environment && cron -f
