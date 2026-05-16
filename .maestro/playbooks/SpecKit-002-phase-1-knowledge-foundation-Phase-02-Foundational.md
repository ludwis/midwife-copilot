# Phase 02: Foundational — Blocking Prerequisites

Implement the core infrastructure that every user story depends on: the FastAPI app factory, X-Admin-Token auth middleware, audit event writer, and the Vue/Firebase frontend bootstrap. This phase MUST be complete before any user story work begins — nothing in Phase 03–06 is possible without it.

## Spec Kit Context

- **Feature:** 002-phase-1-knowledge-foundation
- **Specification:** specs/002-phase-1-knowledge-foundation/spec.md
- **Plan:** specs/002-phase-1-knowledge-foundation/plan.md
- **Data Model:** specs/002-phase-1-knowledge-foundation/data-model.md
- **Contracts:** specs/002-phase-1-knowledge-foundation/contracts/

## Tasks

- [x] T014 Create `backend/api/main.py` (FastAPI app factory: include `admin/kb` router under `/api/admin`; apply auth dependency globally to `/api/admin`; mount `frontend/dist` as StaticFiles at `/`; lifespan startup: load spaCy model once into module-level variable)
  <!-- Done: created backend/api/main.py with asynccontextmanager lifespan (spaCy load), kb_router mounted at /api/admin with Depends(require_admin_token), StaticFiles at / gated on frontend/dist existence (addresses F1). Supporting files created: api/__init__.py, api/admin/__init__.py, api/admin/kb/__init__.py (empty router), core/__init__.py, api/auth.py (T015 stub — correct Security/APIKeyHeader interface). -->
- [ ] T015 Implement X-Admin-Token middleware in `backend/api/auth.py` (FastAPI `Security` dependency: read `X-Admin-Token` header, compare to `ADMIN_TOKEN` env var with `secrets.compare_digest`, raise `HTTPException(401)` on mismatch; import and apply in `main.py`)
- [ ] T016 Implement audit event writer in `backend/core/audit.py` (`write_event(event_type: str, actor: str, **fields)`: serialize to JSONL with ISO-8601 UTC timestamp; dual-write: `google.cloud.logging` structured entry + append line to `gs://midwife-bot-audit-{env}/{YYYY}/{MM}/{DD}/audit.jsonl` via `google.cloud.storage`; GCS client initialized once at module level from `AUDIT_BUCKET_NAME` env var)
- [ ] T017 Create `frontend/src/main.ts` (initialize Firebase app with project config from `import.meta.env`; create Vue app; install Pinia and Router; mount to `#app`)
- [ ] T018 [P] Create `frontend/src/App.vue` (root component: `<RouterView>` wrapped in a global loading overlay that reads from `authStore.loading`)
- [ ] T019 Create `frontend/src/router/index.ts` (Vue Router createWebHistory; routes: `/` redirect to `/kb`, `/login` → LoginPage, `/kb` → KbReviewPage; navigation guard: `router.beforeEach` — if route requires auth and `authStore.isAuthenticated` is false, redirect to `/login`)
- [ ] T020 Create `frontend/src/stores/auth.ts` (Pinia store: `user` state from `onAuthStateChanged`; `signInWithGoogle()` calls `signInWithPopup(provider)` with `GoogleAuthProvider`; `signOut()`; `isAuthenticated` computed; on auth state change, reject user whose `email` does not match `VITE_ADMIN_EMAIL`; `loading` boolean true until first auth state resolved)

## Completion

- [ ] Verify `backend/api/main.py` starts without error: `uvicorn api.main:app --reload` (check for import errors)
- [ ] Verify auth middleware rejects requests without a valid `X-Admin-Token` header (returns 401)
- [ ] Verify `backend/core/audit.py` `write_event()` can be called without raising exceptions (may need mocked GCS for local test)
- [ ] Verify `frontend/src/main.ts`, `App.vue`, `router/index.ts`, and `stores/auth.ts` all exist and have no TypeScript errors
- [ ] Run `/speckit-analyze` to verify consistency
