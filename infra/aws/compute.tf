terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# AMI mais recente do Ubuntu 22.04 LTS
data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical
}

# Chave SSH Dinâmica
resource "tls_private_key" "rsa" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "bot_key" {
  key_name   = "${var.project_name}-DeployKey"
  public_key = tls_private_key.rsa.public_key_openssh
}

resource "local_file" "bot_private_key" {
  content         = tls_private_key.rsa.private_key_pem
  filename        = "${path.module}/meridian_deploy_key.pem"
  file_permission = "0400"
}

# Instância EC2 (Free Tier)
resource "aws_instance" "bot_server" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = var.instance_type
  key_name      = aws_key_pair.bot_key.key_name

  vpc_security_group_ids = [aws_security_group.bot_sg.id]

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
  }

  # Hardening e Configuração de Inicialização
  user_data = <<-EOF
              #!/bin/bash
              apt-get update
              
              # Hardening Básico
              apt-get install -y fail2ban ufw logrotate docker.io docker-compose git
              
              # Firewall
              ufw default deny incoming
              ufw default allow outgoing
              ufw allow ssh
              echo "y" | ufw enable
              
              # Habilitar Docker
              systemctl enable docker
              systemctl start docker

              # Preparar pasta da aplicacao
              mkdir -p /app/Meridian
              chown -R ubuntu:ubuntu /app
              EOF

  tags = {
    Name = var.project_name
  }
}
