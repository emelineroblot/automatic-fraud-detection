output "airflow_url" {
  value = "http://${aws_instance.airflow.public_ip}:8080"
}

output "mlflow_url" {
  value = "http://${aws_instance.airflow.public_ip}:5000"
}

output "dashboard_url" {
  value = "http://${aws_instance.airflow.public_ip}:8501"
}

output "airflow_login" {
  value     = "airflow / ${random_password.airflow_admin.result}"
  sensitive = true
}

output "ssh" {
  value = "ssh -i infra/terraform/keys/fraud-detection.pem ubuntu@${aws_instance.airflow.public_ip}"
}

output "bootstrap_log" {
  value = "ssh -i infra/terraform/keys/fraud-detection.pem ubuntu@${aws_instance.airflow.public_ip} 'sudo tail -f /var/log/fraud-bootstrap.log'"
}

output "psql_fraud" {
  value     = "PGPASSWORD='${random_password.db_fraud.result}' psql -h ${aws_instance.airflow.public_ip} -U fraud -d fraud"
  sensitive = true
}

output "s3_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "instance_id" {
  value = aws_instance.airflow.id
}
