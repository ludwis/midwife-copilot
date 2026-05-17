"""Firebase Function: enqueue kb_imports/{importId} into Cloud Tasks."""
import logging
import os

import firebase_admin
from firebase_functions import firestore_fn
from google.cloud import tasks_v2
from google.protobuf import duration_pb2

firebase_admin.initialize_app()

CLOUD_TASKS_QUEUE = os.environ.get("CLOUD_TASKS_QUEUE", "")
CLOUD_RUN_SERVICE_URL = os.environ.get("CLOUD_RUN_SERVICE_URL", "")
TASKS_SA_EMAIL = os.environ.get("TASKS_SA_EMAIL", "")

logger = logging.getLogger(__name__)


@firestore_fn.on_document_created(
    document="kb_imports/{importId}",
    region="europe-west1",
    memory=256,
    timeout_sec=60,
)
def extract_kb_import(event: firestore_fn.Event) -> None:
    """Enqueue a Cloud Tasks task to process the KB import pipeline."""
    import_id = event.params["importId"]
    logger.info("Enqueuing KB pipeline task for import %s", import_id)

    tasks_client = tasks_v2.CloudTasksClient()
    task = tasks_v2.Task(
        http_request=tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST,
            url=f"{CLOUD_RUN_SERVICE_URL}/internal/kb/process-import/{import_id}",
            oidc_token=tasks_v2.OidcToken(
                service_account_email=TASKS_SA_EMAIL,
                audience=CLOUD_RUN_SERVICE_URL,
            ),
        ),
        dispatch_deadline=duration_pb2.Duration(seconds=3600),
    )
    tasks_client.create_task(parent=CLOUD_TASKS_QUEUE, task=task)
    logger.info("Cloud Tasks task enqueued for import %s", import_id)
