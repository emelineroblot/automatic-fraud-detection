# Infrastructure AWS (Terraform)

```bash
cp terraform.tfvars.example terraform.tfvars   # renseigner discord_webhook_url
bash infra/terraform/tf.sh init
bash infra/terraform/tf.sh apply               # ≈ 8 min (RDS) + ≈ 25 min de bootstrap sur l'EC2 (build, entraînement)
bash infra/terraform/tf.sh output              # airflow_url, mlflow_url, dashboard_url, ssh, s3_bucket
bash infra/terraform/tf.sh output -raw airflow_login
bash infra/terraform/tf.sh destroy             # après la soutenance
```

Voir `docs/deployment-aws.md`.
