import logging

from settings import StorageSettings


logger = logging.getLogger(__name__)


def create_s3_client(settings: StorageSettings):
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint,
        aws_access_key_id=settings.access_key,
        aws_secret_access_key=settings.secret_key,
        config=Config(signature_version="s3v4"),
        region_name=settings.region,
    )


def ensure_bucket(client, settings: StorageSettings) -> None:
    try:
        client.head_bucket(Bucket=settings.bucket)
        return
    except Exception as exc:
        response = getattr(exc, "response", {})
        error_code = str(response.get("Error", {}).get("Code", ""))
        if error_code not in {"404", "NoSuchBucket", "NotFound"}:
            raise

    if not settings.auto_create_bucket:
        raise RuntimeError(
            f"Bucket {settings.bucket!r} does not exist and S3_AUTO_CREATE_BUCKET is disabled"
        )

    logger.info("Creating missing S3 bucket: %s", settings.bucket)
    create_arguments = {"Bucket": settings.bucket}
    if settings.region != "us-east-1":
        create_arguments["CreateBucketConfiguration"] = {
            "LocationConstraint": settings.region
        }
    client.create_bucket(**create_arguments)
