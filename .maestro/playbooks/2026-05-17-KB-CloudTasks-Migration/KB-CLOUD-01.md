# KB Cloud Tasks Migration — Phase 1: Dependencies & Infrastructure Config

The Firebase Cloud Function `extract_kb_import` times out at 9 minutes (GCP hard limit for
Firestore-triggered 2nd gen functions). The fix is to replace the function body with a
Cloud Tasks enqueue stub and move the full pipeline to a new Cloud Run HTTP endpoint
with a 3600s timeout. This phase updates the dependency lists, Dockerfile, and cloudbuild.yaml
to support the new architecture. No logic changes yet.

**Prerequisite:** Phase 0 must be complete. `backend/functions/main.py` and
`backend/functions/requirements.txt` must exist, and `firebase.json` must point to
`backend/functions/`.

Project: `/Users/ad4m/Projects/stilla-app`
GCP project: `midwife-copilot`, region: `europe-west1`

- [x] Add `google-cloud-tasks>=2.16.0` to `backend/requirements.txt` (Cloud Run deps):
  - Read the file first to find the right place (after the existing `google-cloud-*` entries)
  - Add the line: `google-cloud-tasks>=2.16.0`
  - Note: `google-cloud-tasks` is also listed in `backend/functions/requirements.txt`
    (added in Phase 0) — both files need it independently since they serve different containers
  - Do not change any other dependency

- [x] Update `backend/Dockerfile` to prevent uvicorn from killing long-running requests:
  - Read the Dockerfile to find the `CMD` line
  - The uvicorn `--timeout` flag controls worker graceful shutdown; it defaults to 30s and will kill a 40-minute pipeline request
  - Add `--timeout 0` to the existing uvicorn CMD arguments (after `--timeout-keep-alive 75`)
  - Example of what the CMD should look like after: `CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75 --timeout 0"]`
  - Do not change anything else in the Dockerfile

- [x] Update `backend/cloudbuild.yaml` — add Cloud Run timeout, concurrency, and tasks queue creation:
  - Read the full file first
  - In the `gcloud run deploy` step (the step that deploys the FastAPI backend to Cloud Run), add two flags: `--timeout=3600` and `--concurrency=1`
    - `--timeout=3600` sets the max request duration to 60 minutes for long KB imports
    - `--concurrency=1` ensures each Cloud Run instance handles only one pipeline request at a time (the pipeline is CPU/memory-intensive)
  - After the Cloud Run deploy step, add a new step to create the Cloud Tasks queue (use `||true` so it does not fail if the queue already exists):
    ```yaml
    - id: create-tasks-queue
      name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
      entrypoint: bash
      args:
        - '-c'
        - |
          gcloud tasks queues create kb-pipeline \
            --location=europe-west1 \
            --max-attempts=3 \
            --min-backoff=60s \
            --max-backoff=300s \
            --max-doublings=3 \
            --max-dispatches-per-second=1 \
            || true
      waitFor:
        - cloud-run-deploy
    ```
  - Add an IAM binding step after `create-tasks-queue` that grants the Firebase Functions service account permission to enqueue tasks:
    ```yaml
    - id: grant-tasks-enqueuer
      name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
      entrypoint: bash
      args:
        - '-c'
        - |
          gcloud projects add-iam-policy-binding $PROJECT_ID \
            --member="serviceAccount:$PROJECT_ID@appspot.gserviceaccount.com" \
            --role="roles/cloudtasks.enqueuer" \
            || true
      waitFor:
        - create-tasks-queue
    ```
  - In the Firebase Functions deploy step, confirm it references `source: backend/functions`
    (this should already be set by Phase 0's firebase.json update; just verify)
  - Verify the YAML is valid after edits (no duplicate keys, correct indentation)
