terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Configure the AWS Provider
provider "aws" {
  region = "sa-east-1" # Data Center em São Paulo (melhor latência para B3)
}

# Pegar a AMI mais recente do Ubuntu 22.04 LTS
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

# Grupo de Segurança: Bloqueado, liberando apenas SSH
resource "aws_security_group" "bot_sg" {
  name        = "meridian_bot_sg"
  description = "Security Group for Meridian Trading Bot"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # TODO: Trocar pelo IP do usuario na producao final
  }

  egress {
    description = "Allow outbound traffic (HTTP/HTTPS)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# A chave SSH para acesso ao servidor
resource "tls_private_key" "rsa" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "bot_key" {
  key_name   = "meridian_deploy_key"
  public_key = tls_private_key.rsa.public_key_openssh
}

# Salvar a chave privada localmente
resource "local_file" "bot_private_key" {
  content         = tls_private_key.rsa.private_key_pem
  filename        = "${path.module}/meridian_deploy_key.pem"
  file_permission = "0400"
}

# A Instância EC2 (Free Tier)
resource "aws_instance" "bot_server" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = "t3.micro" # Free Tier em sa-east-1
  key_name      = aws_key_pair.bot_key.key_name

  vpc_security_group_ids = [aws_security_group.bot_sg.id]

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
  }

  # Script executado ao ligar o servidor (User Data)
  user_data = <<-EOF
              #!/bin/bash
              apt-get update
              apt-get install -y docker.io docker-compose git
              systemctl enable docker
              systemctl start docker
              
              # Prepara o diretório da aplicação
              mkdir -p /app/Meridian
              cd /app
              # Aqui o deployer irá clonar o repositório ou copiar via scp
              EOF

  tags = {
    Name = "Meridian-Bot-Prod"
  }
}

output "instance_public_ip" {
  description = "IP Público do Servidor EC2"
  value       = aws_instance.bot_server.public_ip
}
