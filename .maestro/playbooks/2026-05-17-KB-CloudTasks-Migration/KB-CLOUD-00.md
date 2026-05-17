# KB Cloud Tasks Migration — Phase 0: Backend Folder Restructuring

The `backend/` folder currently serves two GCP deployment targets (Firebase Cloud Function +
Cloud Run) through implicit conventions: `firebase.json` ignore lists, a Dockerfile that
only Cloud Run uses, and a shared `requirements.txt` with deps for both. This phase gives
each target its own clearly bounded directory before any logic changes are made.

**Target structure after this phase:**
```
backend/
├── functions/          # Firebase Cloud Functions (self-contained)
│   ├── main.py         # extract_kb_import (moved from backend/main.py)
│   └── requirements.txt  # Minimal: firebase-functions, firebase-admin, google-cloud-tasks
├── api/                # Cloud Run FastAPI (unchanged, stays here)
├── bot/                # Shared KB pipeline logic (unchanged)
├── core/               # Shared utilities (unchanged)
├── Dockerfile          # Cloud Run container (unchanged)
├── requirements.txt    # Cloud Run deps (firebase-functions removed)
└── tests/
```

Project: `/Users/ad4m/Projects/stilla-app`

- [x] Move `backend/main.py` into a new `backend/functions/` package:
  - Create directory `backend/functions/` (just create the files below — no mkdir needed)
  - Create `backend/functions/__init__.py` as an empty file
  - Move the content of `backend/main.py` to `backend/functions/main.py` (copy content, then delete original)
    - The file content does NOT change in this step — this is a pure move
    - The relative imports inside the file (e.g. `from bot.kb...`, `from core.audit...`) will
      still resolve correctly because `backend/` is the Python working directory for both
      Firebase Functions deployment and tests
  - Delete `backend/main.py` after the content is in `backend/functions/main.py`
  - Confirm: `backend/functions/main.py` exists, `backend/main.py` does not

- [x] Create `backend/functions/requirements.txt` with minimal Firebase Function deps:
  - The Cloud Function after the migration (Phase 2) only needs three packages.
    Even now (before Phase 2 rewrites the logic), create this file with the final
    target deps so the structure is in place. Firebase CLI uses this file to install
    deps for the function; the full `backend/requirements.txt` is for Cloud Run only.
  - File contents:
    ```
    firebase-functions>=0.1.0
    firebase-admin>=6.0.0
    google-cloud-tasks>=2.16.0
    google-protobuf>=4.0.0
    ```
  - Note: The current `backend/functions/main.py` still imports `bot.kb.*` and other heavy
    deps until Phase 2 rewrites it. That's fine — Firebase CLI reads `requirements.txt` at
    deploy time, not at restructure time. Phase 2 will rewrite the function body to only
    need these four packages.

- [x] Update `firebase.json` to point to `backend/functions/` as the functions source:
  - Read `firebase.json` first
  - Change `"source": "backend"` → `"source": "backend/functions"`
  - Remove the entire `"ignore"` array — it is no longer needed since `backend/functions/`
    contains only function code (no `api/`, `tests/`, `Dockerfile` to exclude)
  - The result should be:
    ```json
    "functions": {
      "source": "backend/functions",
      "runtime": "python312"
    }
    ```
  - Do not change any other section of `firebase.json`

- [x] Remove `firebase-functions` from `backend/requirements.txt`:
  - Read `backend/requirements.txt`
  - Delete the line `firebase-functions>=0.1.0` (it is now only in `backend/functions/requirements.txt`)
  - Keep `firebase-admin` — it is still used by Cloud Run for Firestore access
  - Do not change any other dependency

- [x] Update test imports to reflect the new location of `main.py`:
  - Read `backend/tests/integration/test_extract_function.py`
  - Find the import line that imports `extract_kb_import` from `main` (e.g. `from main import extract_kb_import` or `import main`)
  - Update it to `from functions.main import extract_kb_import` (or `import functions.main as main`)
  - Also check `backend/tests/integration/conftest.py` for any import of `main` and update it the same way
  - Run: `cd /Users/ad4m/Projects/stilla-app/backend && python -m pytest tests/ -x -q 2>&1 | tail -20`
  - All tests must pass after the move — no logic has changed, only the file location

- [x] Verify `backend/functions/main.py` is importable from the backend root:
  - Run: `cd /Users/ad4m/Projects/stilla-app/backend && python -c "from functions.main import extract_kb_import; print('OK')" 2>&1`
  - If it fails, check for sys.path issues — the working directory must be `backend/` for the
    relative imports (`from bot.kb...`) to resolve
  - Fix any import errors before proceeding to Phase 1
