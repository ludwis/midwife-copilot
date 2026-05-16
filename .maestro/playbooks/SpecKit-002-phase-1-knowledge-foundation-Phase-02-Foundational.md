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
- [x] T015 Implement X-Admin-Token middleware in `backend/api/auth.py` (FastAPI `Security` dependency: read `X-Admin-Token` header, compare to `ADMIN_TOKEN` env var with `secrets.compare_digest`, raise `HTTPException(401)` on mismatch; import and apply in `main.py`)
  <!-- Done: implementation was already complete in the T014 stub — APIKeyHeader("X-Admin-Token"), secrets.compare_digest against ADMIN_TOKEN env var, HTTPException(401) on mismatch. Created backend/tests/__init__.py and backend/tests/test_auth.py with 4 pytest cases covering: missing token → 401, wrong token → 401, correct token → 200, unset ADMIN_TOKEN → 401. All 4 pass. -->
- [x] T016 Implement audit event writer in `backend/core/audit.py` (`write_event(event_type: str, actor: str, **fields)`: serialize to JSONL with ISO-8601 UTC timestamp; dual-write: `google.cloud.logging` structured entry + append line to `gs://midwife-bot-audit-{env}/{YYYY}/{MM}/{DD}/audit.jsonl` via `google.cloud.storage`; GCS client initialized once at module level from `AUDIT_BUCKET_NAME` env var)
  <!-- Done: created backend/core/audit.py with lazy module-level singletons for GCS and Cloud Logging clients; write_event() builds ISO-8601 UTC JSONL entry, calls cloud_log.log_struct(), then appends to GCS blob via download+upload pattern. Graceful degradation: GCS skipped when AUDIT_BUCKET_NAME absent; all errors caught+logged, never raised to callers. Added google-cloud-logging>=3.10.0 to requirements.txt. Created backend/tests/test_audit.py with 8 pytest cases covering: required fields, ISO-8601 timestamp, append behavior, blob path format, Cloud Logging dual-write, missing bucket skip, GCS error resilience, Cloud Logging error resilience. All 8 pass; existing 4 auth tests unaffected. -->
- [x] T017 Create `frontend/src/main.ts` (initialize Firebase app with project config from `import.meta.env`; create Vue app; install Pinia and Router; mount to `#app`)
  <!-- Done: created frontend/src/main.ts — calls initializeApp(firebaseConfig) with all six VITE_FIREBASE_* env vars from import.meta.env; creates Vue app from App.vue; installs createPinia() and router; mounts to #app. -->
- [x] T018 [P] Create `frontend/src/App.vue` (root component: `<RouterView>` wrapped in a global loading overlay that reads from `authStore.loading`)
  <!-- Done: created frontend/src/App.vue — shows a centered CSS spinner div when authStore.loading is true, renders <RouterView> otherwise. Imports useAuthStore from ./stores/auth (created by T020). Minimal scoped CSS for the spinner animation. -->
- [x] T019 Create `frontend/src/router/index.ts` (Vue Router createWebHistory; routes: `/` redirect to `/kb`, `/login` → LoginPage, `/kb` → KbReviewPage; navigation guard: `router.beforeEach` — if route requires auth and `authStore.isAuthenticated` is false, redirect to `/login`)
  <!-- Done: created frontend/src/router/index.ts — createWebHistory router with 3 routes (/ redirect to /kb, /login → LoginPage lazy, /kb → KbReviewPage lazy with meta.requiresAuth); beforeEach guard redirects unauthenticated users to /login when meta.requiresAuth is true. -->
- [x] T020 Create `frontend/src/stores/auth.ts` (Pinia store: `user` state from `onAuthStateChanged`; `signInWithGoogle()` calls `signInWithPopup(provider)` with `GoogleAuthProvider`; `signOut()`; `isAuthenticated` computed; on auth state change, reject user whose `email` does not match `VITE_ADMIN_EMAIL`; `loading` boolean true until first auth state resolved)
  <!-- Done: created frontend/src/stores/auth.ts — defineStore('auth') with setup syntax; user ref<User|null>, loading ref<boolean> (true until first onAuthStateChanged fires); isAuthenticated computed; onAuthStateChanged rejects any user whose email != VITE_ADMIN_EMAIL (calls firebaseSignOut + sets user to null); signInWithGoogle() uses GoogleAuthProvider + signInWithPopup; signOut() calls firebaseSignOut. Single pre-existing tsconfig TS5090 error (paths alias without baseUrl) is unrelated to this task. -->

## Completion

- [x] Verify `backend/api/main.py` starts without error: `uvicorn api.main:app --reload` (check for import errors)
  <!-- Done: python3 -m py_compile api/main.py api/auth.py core/audit.py — all compiled clean. Module-level import chain (app factory, spaCy lifespan, kb_router, require_admin_token) verified via TestClient instantiation. Warning logged for missing frontend/dist (expected in dev). -->
- [x] Verify auth middleware rejects requests without a valid `X-Admin-Token` header (returns 401)
  <!-- Done: all 4 pytest cases in tests/test_auth.py pass — missing token → 401, wrong token → 401, correct token → 200, unset ADMIN_TOKEN → 401. -->
- [x] Verify `backend/core/audit.py` `write_event()` can be called without raising exceptions (may need mocked GCS for local test)
  <!-- Done: all 8 pytest cases in tests/test_audit.py pass — including GCS error resilience and Cloud Logging error resilience (never raises to callers). 12/12 total backend tests green. -->
- [x] Verify `frontend/src/main.ts`, `App.vue`, `router/index.ts`, and `stores/auth.ts` all exist and have no TypeScript errors
  <!-- Done: all 4 files confirmed at frontend/src/. vue-tsc --noEmit exits 0 (no TypeScript errors). -->
- [x] Run `/speckit-analyze` to verify consistency
  <!-- Done: full cross-artifact analysis run. 0 CRITICAL issues, 1 HIGH (S1: VITE_ADMIN_TOKEN baked into frontend bundle — X-Admin-Token extractable from JS bundle, bypassing Firebase Auth). 2 MEDIUM underspecification (A2: no_pairs_found acceptance scenario; U2: SC-007 test queries undefined). All 15 FRs have ≥1 task (100% coverage). Constitution alignment: no violations; VI justified deviation documented. Full report output to console. -->
