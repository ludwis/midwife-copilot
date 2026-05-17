# KB Cloud Tasks Migration — Phase 2: Firebase Function Stub

Replace the full pipeline body of `extract_kb_import` in `backend/functions/main.py` with a
lightweight Cloud Tasks enqueue stub. The function should complete in ~200ms instead of
timing out after 9 minutes. The actual pipeline will be handled by a new Cloud Run
HTTP endpoint (created in Phase 3).

**Prerequisite:** Phase 0 must be complete. The file being rewritten is
`backend/functions/main.py` (moved from `backend/main.py` in Phase 0).

Project: `/Users/ad4m/Projects/stilla-app`
GCP project: `midwife-copilot`, region: `europe-west1`

**Context on the current file (`backend/functions/main.py`):**
- It currently imports `bot.kb.*`, `core.audit`, `google.cloud.storage`, `tempfile`, and runs the
  full parse → PII strip → Gemini extract → stage pipeline inside the function body
- The function is decorated with `@firestore_fn.on_document_created` listening to `kb_imports/{importId}`
- The timeout is currently set to `timeout_sec=540` (9-minute hard cap)
- After this phase, the function only needs packages in `backend/functions/requirements.txt`
  (firebase-functions, firebase-admin, google-cloud-tasks, google-protobuf) — no bot.kb.* imports

**New behaviour:**
The function should:
1. Extract `import_id` from `event.params["importId"]`
2. Enqueue a Cloud Tasks HTTP task targeting `{CLOUD_RUN_SERVICE_URL}/internal/kb/process-import/{import_id}`
   - Use OIDC authentication with service account `TASKS_SA_EMAIL`
   - Set `dispatch_deadline` to 3600 seconds
3. Log that the task was enqueued and return

**New env vars the function needs** (read from `os.environ`):
- `CLOUD_TASKS_QUEUE`: full queue path, e.g. `projects/midwife-copilot/locations/europe-west1/queues/kb-pipeline`
- `CLOUD_RUN_SERVICE_URL`: the Cloud Run service URL, e.g. `https://stilla-backend-xxx-ew.a.run.app`
- `TASKS_SA_EMAIL`: the invoker service account, e.g. `kb-pipeline-invoker@midwife-copilot.iam.gserviceaccount.com`

- [x] Rewrite `backend/functions/main.py` to be a lightweight Cloud Tasks enqueue stub:
  - Read the current `backend/functions/main.py` to understand all imports and the full function body
  - Remove all imports that are only needed by the pipeline: `bot.kb.*`, `core.audit`,
    `google.cloud.storage`, `tempfile`, `asyncio`, `pydantic`, `pathlib`
  - Keep: `firebase_functions.firestore_fn`, `firebase_admin`, `os`, `logging`
  - Add: `from google.cloud import tasks_v2` and `from google.protobuf import duration_pb2`
  - Read the three new env vars at module level (after `firebase_admin.initialize_app()`):
    ```python
    CLOUD_TASKS_QUEUE = os.environ.get("CLOUD_TASKS_QUEUE", "")
    CLOUD_RUN_SERVICE_URL = os.environ.get("CLOUD_RUN_SERVICE_URL", "")
    TASKS_SA_EMAIL = os.environ.get("TASKS_SA_EMAIL", "")
    ```
  - Update the `@firestore_fn.on_document_created` decorator: keep `document`, `region`, change
    `memory=256` and `timeout_sec=60` (the stub needs much less)
  - Replace the entire function body with:
    ```python
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
    ```
  - Verify: the final file should be under 40 lines total
  - Do not change `firebase.json` (already updated in Phase 0)

- [x] Verify the stub file is importable and has no syntax errors:
  - Run: `cd /Users/ad4m/Projects/stilla-app/backend && python -c "from functions.main import extract_kb_import; print('OK')" 2>&1`
  - If there are import errors due to missing `google-cloud-tasks`, install it:
    `pip install google-cloud-tasks>=2.16.0`
  - Fix any syntax or import errors until the command prints `OK`
  - Note: `google-cloud-tasks` may already be transitively installed; check with
    `pip show google-cloud-tasks` before installing
