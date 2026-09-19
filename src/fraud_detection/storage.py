"""Archivage des exports dans S3 (production). Sans REPORTS_S3_BUCKET, ne fait rien."""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def upload_report(local_path: str | Path, bucket: str | None = None, prefix: str = "reports") -> str | None:
    """Copie le fichier dans s3://<bucket>/<prefix>/<nom> ; renvoie l'URI S3, ou None si pas de bucket configuré.

    Les identifiants viennent de la chaîne boto3 standard (rôle d'instance EC2 en production).
    """
    bucket = bucket or os.getenv("REPORTS_S3_BUCKET") or None
    if not bucket:
        log.info("REPORTS_S3_BUCKET non défini : export conservé en local uniquement (%s)", local_path)
        return None
    import boto3  # import différé : inutile en dev

    key = f"{prefix}/{Path(local_path).name}"
    boto3.client("s3").upload_file(str(local_path), bucket, key)
    uri = f"s3://{bucket}/{key}"
    log.info("Export archivé -> %s", uri)
    return uri
