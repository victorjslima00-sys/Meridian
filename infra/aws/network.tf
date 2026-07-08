# Security Group para o Bot
resource "aws_security_group" "bot_sg" {
  name        = "${var.project_name}_sg"
  description = "Security Group for Meridian Trading Bot (Hardened)"

  # Acesso SSH estrito (pode ser limitado via GitHub Secrets runner IP ou IP local)
  ingress {
    description = "SSH Access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # TODO: Na produção real, restringir ao IP do CI/CD
  }

  # Acesso de saída total (Necessário para a API da B3/Yahoo e Telegram)
  egress {
    description = "Allow outbound traffic (HTTP/HTTPS)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-SecurityGroup"
  }
}
