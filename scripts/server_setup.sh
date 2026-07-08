#!/bin/bash
# Script de provisionamento (User Data fallback / Manual Setup)
set -e

echo "=> Iniciando Hardening e Configuração do Servidor Meridian..."

# 1. Update e Instalações Básicas
sudo apt-get update
sudo apt-get install -y fail2ban ufw logrotate docker.io docker-compose git

# 2. Hardening SSH e Fail2Ban
echo "=> Configurando Fail2Ban..."
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

echo "=> Bloqueando login de root por SSH..."
sudo sed -i 's/^PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# 3. Firewall (UFW)
echo "=> Configurando Firewall (UFW)..."
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
# Necessário apenas se rodar alguma API Web. Atualmente o bot só faz requisições OUTGOING.
# sudo ufw allow 80/tcp 
echo "y" | sudo ufw enable

# 4. Configuração de Logrotate do Docker
echo "=> Configurando Logrotate para os containers Docker..."
cat <<EOF | sudo tee /etc/logrotate.d/docker-containers
/var/lib/docker/containers/*/*.log {
  rotate 7
  daily
  compress
  size=10M
  missingok
  delaycompress
  copytruncate
}
EOF

# 5. Permissões de Diretório
echo "=> Configurando diretório da aplicação..."
sudo mkdir -p /app/Meridian
sudo chown -R ubuntu:ubuntu /app/Meridian

echo "=> Servidor configurado com sucesso! Segurança Nível Enterprise Ativada."
