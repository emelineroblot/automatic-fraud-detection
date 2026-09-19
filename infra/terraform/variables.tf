variable "region" {
  description = "Région AWS (Stockholm : résidence des données UE)"
  type        = string
  default     = "eu-north-1"
}

variable "repo_url" {
  description = "Dépôt public cloné par l'instance au démarrage"
  type        = string
  default     = "https://github.com/emelineroblot/automatic-fraud-detection.git"
}

variable "repo_ref" {
  description = "Branche ou tag déployé"
  type        = string
  default     = "main"
}

variable "ec2_instance_type" {
  description = "Airflow 3 + MLflow + Streamlit + entraînement : 8 Go de RAM (type éligible free tier sur ce compte)"
  type        = string
  default     = "m7i-flex.large"
}

variable "rds_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "operator_cidr" {
  description = "CIDR autorisé (SSH, UIs, psql). Vide = IP publique courante détectée automatiquement"
  type        = string
  default     = ""
}

variable "dataset_path" {
  description = "Chemin local du CSV d'entraînement, poussé dans S3 (relatif au dossier terraform)"
  type        = string
  default     = "../../contexte/fraudTest.csv"
}

variable "discord_webhook_url" {
  description = "Webhook Discord (alertes + rapport). À renseigner dans terraform.tfvars (gitignoré)"
  type        = string
  sensitive   = true
}

variable "fraud_threshold" {
  type    = number
  default = 0.5
}

variable "report_timezone" {
  type    = string
  default = "Europe/Paris"
}
