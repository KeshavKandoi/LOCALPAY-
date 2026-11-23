from celery import Celery

from app.core.settings import get_settings

settings = get_settings()
redis_url = str(settings.redis_url)
celery_app = Celery("localpay", broker=redis_url, backend=redis_url)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    broker_connection_retry_on_startup=True,
    result_expires=300,
)


@celery_app.task(name="localpay.worker_probe")
def worker_probe(nonce: str) -> str:
    return nonce
