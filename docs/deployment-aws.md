# Déploiement en production (AWS)

> Le pipeline tourne dans le cloud : infrastructure déclarée en **Terraform**, orchestration **Airflow 3**
> sur une **EC2**, dataset / artefacts MLflow / rapports dans **S3**. Ce document décrit ce qui est
> déployé, comment le reproduire, et ce qui diffère de la stack de développement.

- Infrastructure : [`infra/terraform/`](../infra/terraform/) (`main.tf`, `variables.tf`, `outputs.tf`, `user_data.sh`, `tf.sh`)
- Stack : [`docker/prod/docker-compose.yml`](../docker/prod/docker-compose.yml)
- Région : **eu-north-1 (Stockholm)** — résidence des données UE

---

## 1. Architecture déployée

```mermaid
flowchart TB
    OP["Poste opérateur — IP unique autorisée<br/>terraform apply · Airflow :8080 · MLflow :5000 · Dashboard :8501"]
    GH[("GitHub<br/>automatic-fraud-detection")]
    API["API temps réel (HF Space)<br/>1 transaction / minute"]

    subgraph AWS["AWS eu-north-1 — VPC par défaut — 19 ressources Terraform"]
        subgraph EC2["EC2 m7i-flex.large · EBS 30 Go chiffré · rôle d'instance (S3) · docker compose"]
            AF["Airflow 3<br/>api-server · scheduler · dag-processor<br/>DAG fraud_realtime · DAG fraud_daily_report"]
            MLF["MLflow 3 server<br/>registry : fraud_detection@production"]
            TRN["training<br/>one-shot au boot"]
            PG[("PostgreSQL 16<br/>airflow · mlflow · fraud")]
            DASH["Streamlit"]
        end
        S3[("S3 — chiffré, versionné<br/>data/fraudTest.csv · mlflow-artifacts/ · reports/")]
    end

    DISC["Discord<br/>alerte fraude · rapport quotidien"]

    OP -- "terraform apply" --> AWS
    GH -- "git clone au boot" --> EC2
    API -- "GET chaque minute" --> AF
    S3 -- "dataset" --> TRN
    TRN -- "log_model + alias" --> MLF
    MLF -- "load_model" --> AF
    MLF -- "artefacts" --> S3
    AF -- "transactions · prédictions" --> PG
    MLF -- "backend store" --> PG
    PG --> DASH
    AF -- "CSV quotidien" --> S3
    AF -- "webhook" --> DISC
```

| Brique | Développement (`docker/dev/`) | Production (`docker/prod/` + Terraform) |
|---|---|---|
| PostgreSQL | conteneur, 3 bases créées par le script d'init | **même conteneur**, volume Docker sur l'EBS chiffré, mots de passe générés par Terraform. **RDS était la cible** (`db.t4g.micro`) : bloqué par le quota du plan gratuit du compte (1 instance RDS, déjà utilisée par un autre projet) |
| Artefacts MLflow | volume Docker | **S3** `mlflow-artifacts/` (`--artifacts-destination`, rôle d'instance) |
| Dataset | `contexte/fraudTest.csv` local | **S3** `data/fraudTest.csv`, poussé par Terraform, téléchargé par l'instance |
| Entraînement | `python training/train.py` sur le poste | conteneur `training` (python 3.13, même version que l'image Airflow), lancé une fois au boot |
| Rapports quotidiens | `reports/` local | `reports/` local **+ S3** `reports/transactions_<date>.csv` (tâche `archive_s3`) |
| Code | bind-mount `src/` (hot reload) | copié dans l'image ; DAGs depuis le clone git |
| Secrets | `.env` écrit à la main | **générés par Terraform** (`random_password`, `random_bytes` pour Fernet), écrits dans `/opt/fraud/.env` (`chmod 600`) |
| Accès | `localhost` | UIs (8080, 5000, 8501) **publiques** pour la démo (`ui_cidr`, défaut `0.0.0.0/0`) ; SSH et 5432 restreints à **l'IP publique de l'opérateur** |

## 2. Ce que fait `user_data.sh` au premier démarrage

1. Installe Docker, compose, AWS CLI v2.
2. Clone le dépôt (`repo_ref`, défaut `main`) dans `/opt/fraud`.
3. Écrit `.env` avec les secrets Terraform (Postgres, Fernet, JWT, admin Airflow, webhook Discord, bucket).
4. Télécharge le dataset depuis S3.
5. `docker compose build && up -d` (prod) — le conteneur Postgres crée les 3 bases et le schéma au premier démarrage.
6. Quand MLflow répond : `--profile train run training` → 3 modèles comparés, le meilleur enregistré avec l'alias `production` (≈ 15 min sur 2 vCPU).
7. Quand Airflow répond : dépause des deux DAGs. Le pipeline temps réel démarre à la minute suivante.

Journal : `/var/log/fraud-bootstrap.log` (commande dans `terraform output bootstrap_log`).

## 3. Reproduire

Prérequis : compte AWS avec droits EC2, S3, IAM ; CLI AWS configurée ; Docker (Terraform s'exécute dans un conteneur, voir §5) ; `contexte/fraudTest.csv` présent.

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars   # discord_webhook_url
bash infra/terraform/tf.sh init
bash infra/terraform/tf.sh apply          # ≈ 2 min, puis ≈ 25 min de bootstrap sur l'EC2
bash infra/terraform/tf.sh output         # airflow_url, mlflow_url, dashboard_url, ssh, s3_bucket
bash infra/terraform/tf.sh output -raw airflow_login
```

Mettre à jour le code déployé : `ssh … 'cd /opt/fraud && sudo git pull'` — les DAGs sont relus toutes les 30 s ; `docker compose … build && up -d` seulement si `src/`, un `Dockerfile` ou `requirements.txt` changent.

**Arrêt** : `bash infra/terraform/tf.sh destroy` — supprime les 19 ressources, bucket inclus (`force_destroy`).

Pause sans détruire (données conservées sur l'EBS, ~0,1 $/jour) : `aws ec2 stop-instances --instance-ids $(bash infra/terraform/tf.sh output -raw instance_id)` ; l'IP publique change au redémarrage (`tf.sh apply -refresh-only` puis `output`).

`user_data_replace_on_change = false` : modifier `user_data.sh` ne recrée pas l'instance ; pour rejouer le bootstrap, `tf.sh taint aws_instance.airflow` puis `apply`.

## 4. Coût

| Ressource | Tarif eu-north-1 | Par jour |
|---|---|---|
| EC2 `m7i-flex.large` | ~0,10 $/h | ~2,4 $ |
| EBS 30 Go gp3 | ~0,09 $/Go/mois | ~0,1 $ |
| S3 (< 200 Mo, versionné) | — | < 0,01 $ |
| **Total** | | **≈ 2,5 $/jour** — à détruire après la soutenance |

## 5. Pourquoi `tf.sh` (Terraform dans Docker)

Sous Windows avec un antivirus qui intercepte le TLS, Terraform ne peut pas dialoguer avec ses providers (handshake mTLS local rejeté). Le script exécute `hashicorp/terraform:1.9` dans un conteneur, monte la racine du dépôt (pour lire le CSV) et `~/.aws` en lecture seule, et ajoute le certificat de l'antivirus au bundle du conteneur pour les appels sortants. Sous macOS/Linux, `terraform` natif fonctionne aussi (`cd infra/terraform && terraform …`).

## 6. Sécurité du déploiement

- Aucune clé AWS dans le code ni sur l'instance : S3 est accédé via le **rôle d'instance** (IMDSv2, `hop_limit = 2` pour les conteneurs).
- Mots de passe Postgres, Airflow, clé Fernet et secret JWT **générés** par Terraform, stockés dans l'état local (gitignoré) et dans `.env` sur l'instance.
- Clé SSH générée par Terraform → `infra/terraform/keys/` (gitignoré).
- Security group : SSH et PostgreSQL limités à l'IP de l'opérateur ; les UIs sont ouvertes (`ui_cidr`) pour la soutenance — Airflow est protégé par login, MLflow et Streamlit ne le sont pas : à refermer (`ui_cidr = "<ip>/32"`) ou à mettre derrière un reverse proxy authentifié hors démo.
- Chiffrement at-rest : volume EC2 (Postgres inclus), S3 (AES-256) ; versioning S3 ; bucket privé.
- Limites assumées : UIs en HTTP (pas de TLS, pas de domaine) ; Postgres exposé sur 5432 pour `psql` depuis le poste ; base non managée (pas de sauvegarde automatique — snapshot EBS ou RDS en cible) — acceptable pour une démo restreinte à une IP, pas pour une vraie production (reverse proxy TLS, RDS privé, Secrets Manager).

## 7. Ce que la vidéo montre

1. Console AWS : l'instance `fraud-detection-airflow`, le bucket S3 — ou `terraform output`.
2. Airflow (`http://<ip>:8080`) : la grille de `fraud_realtime`, un run par minute.
3. MLflow (`http://<ip>:5000`) : l'expérience, le registry, les artefacts dans S3.
4. Trigger `fraud_realtime` avec `{"threshold_override": 0}` → alerte Discord.
5. Trigger `fraud_daily_report` → embed Discord avec l'URI S3 du CSV ; le fichier dans le bucket.
6. Dashboard (`http://<ip>:8501`).
