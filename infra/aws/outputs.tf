output "bot_server_ip" {
  description = "IP Público da instância EC2 (Meridian Bot)"
  value       = aws_instance.bot_server.public_ip
}

output "ssh_connection_string" {
  description = "Comando para conectar no servidor via SSH"
  value       = "ssh -i infra/aws/meridian_deploy_key.pem ubuntu@${aws_instance.bot_server.public_ip}"
}
