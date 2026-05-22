# KB Firebase Pipeline — Phase 3: Firebase & Infrastructure Config

Wire the Firebase Function into `firebase.json`, add the GCS imports bucket to
`cloudbuild.yaml`, and update `.env` with the new env var.

- [x] Update `firebase.json` to add the `functions` configuration block:
  - Add a `"functions"` key at the top level with:
    - `"source": "backend/functions"` — points to the function source directory
    - `"runtime": "python312"` — Python 3.12 runtime (matches backend)
    - `"ignore": ["venv", ".venv", "__pycache__", "*.pyc"]`
  - Keep all existing `hosting` and `emulators` config unchanged
  - Run `cat firebase.json` first to confirm current structure before editing

- [x] Update `backend/.env` — add one new env var:
  ```
  # ── KB Import File Storage ────────────────────────────────────────────────────
  # GCS bucket for temporary chat export files (deleted after extraction)
  KB_IMPORTS_BUCKET_NAME=midwife-copilot-kb-imports-dev
  ```

- [x] Update `cloudbuild.yaml` to:
  - Add `_KB_IMPORTS_BUCKET_NAME: midwife-copilot-kb-imports-dev` to the `substitutions` block (or create one if absent)
  - Add a `create-kb-imports-bucket` step after the existing audit bucket step:
    ```yaml
    - id: create-kb-imports-bucket
      name: gcr.io/google.com/cloudsdktool/cloud-sdk
      entrypoint: bash
      args:
        - -c
        - |
          gsutil mb -l europe-west1 gs://$_KB_IMPORTS_BUCKET_NAME || true
          echo '{"rule":[{"action":{"type":"Delete"},"condition":{"age":7}}]}' | \
            gsutil lifecycle set /dev/stdin gs://$_KB_IMPORTS_BUCKET_NAME
    ```
  - Add a `deploy-functions` step after the Cloud Run deploy step:
    ```yaml
    - id: deploy-functions
      name: node:20
      entrypoint: bash
      args:
        - -c
        - |
          npm install -g firebase-tools
          firebase deploy --only functions --project $PROJECT_ID --non-interactive
    ```
  - Read `cloudbuild.yaml` first to understand the current step structure and `waitFor` chain before editing

- [x] Verify config correctness:
  - `python -c "import json; json.load(open('firebase.json'))"` — valid JSON
  - `grep KB_IMPORTS_BUCKET_NAME backend/.env` — var present
  - `grep KB_IMPORTS_BUCKET_NAME cloudbuild.yaml` — bucket creation step present
