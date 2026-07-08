variable "aws_region" {
  description = "Região AWS para deploy"
  type        = string
  default     = "sa-east-1"
}

variable "instance_type" {
  description = "Tipo de instância EC2 (Free Tier Elegível)"
  type        = string
  default     = "t3.micro"
}

variable "project_name" {
  description = "Nome do projeto"
  type        = string
  default     = "Meridian-Bot"
}
