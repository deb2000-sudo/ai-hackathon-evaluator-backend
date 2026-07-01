# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AI Hackathon Evaluator Backend is a FastAPI service whose core feature is **AI-assisted video evaluation**: a participant uploads their hackathon submission video, and the backend uses Vertex AI **Gemini** (multimodal) to watch the video and produce a structured evaluation (per-criterion scores, strengths, improvements, and an overall verdict). Videos are stored in Google Cloud Storage and session metadata in Firestore. Firebase provides authentication and the Firestore database.

The **login / authentication system is reused verbatim** from the NxtCreate backend: Firebase Auth via the Identity Toolkit REST API for login, `id_token` verification for protected routes, Firestore-backed roles, and a startup seeder.

## Commands

```bash
# Install (editable, with dev tools)
pip install -e ".[dev]"

# Run locally with hot reload (serves on :8000; also `python -m app.main`)
uvicorn app.main:app --reload

# Run all tests / a single test
pytest
pytest path/to/test_file.py::test_name

# Format, lint, type-check
black .            # line-length 100
flake8 app
mypy app

# Docker
docker-compose up                 # production-style service on :8000
docker-compose --profile dev up   # hot-reload dev service
```

Note: `pytest`/`pytest-asyncio` are configured as dev dependencies but there is no `tests/` directory yet.

## Architecture

Layered, with a strict dependency direction: **routes → services → `FirebaseService`**. Models are Pydantic schemas; middleware supplies auth dependencies.

- **`app/main.py`** — app factory, CORS allow-list, global `ValueError`→400 / `Exception`→500 handlers, and a `lifespan` that runs `DatabaseSeeder` on startup.
- **`app/routes/`** — `auth` (`/auth`), `admin` (`/admin`), `evaluation` (`/upload-video`, `/analyze-video`, `/evaluations/{id}`). Routers are included in `main.py`.
- **`app/services/`** — business logic. `FirebaseService` is the only thing that touches Firestore/Firebase Auth directly; all other services depend on it.
- **`app/models/`** — Pydantic request/response schemas (`user_model.py`, `evaluation_model.py`).
- **`app/middleware/auth_middleware.py`** — FastAPI dependencies, not ASGI middleware.

### Firebase access pattern

`FirebaseService` (`app/services/firebase.py`) is a **singleton** (`__new__` + `_initialized` guard) that initializes the Firebase Admin SDK from env vars (credentials assembled from `FIREBASE_*` env vars; `FIREBASE_PRIVATE_KEY` has its `\n` escapes un-escaped at runtime). It exposes generic Firestore helpers (`set/get/update/delete_document`, `get_collection`, `query_collection`, `batch_write`) and Auth helpers. **Never import `firebase_admin` directly in routes/services — go through `FirebaseService`.** Firestore is schemaless here; the `users` and `evaluation_sessions` collections are conventions, not enforced models.

### Authentication & authorization

- Login (`POST /auth/login`) does **not** use the Admin SDK to mint tokens. It calls the Firebase Identity Toolkit REST API (`signInWithPassword`) with `FIREBASE_WEB_API_KEY` to obtain an `id_token`, after sanity-checking the token's `aud`/`uid` against the looked-up user.
- Protected routes depend on `get_current_user`, which verifies the bearer `id_token` (normalizing `Bearer`/quotes, pre-checking JWT shape and project `aud` before the SDK call) and then loads the user's Firestore record to attach `role`. A token valid in Firebase but with **no Firestore `users/{uid}` doc → 404**.
- Admin-only routes depend on `get_admin_user`, which requires `role == "admin"`. Roles live in the Firestore user document, not in Firebase custom claims.

### Video evaluation flow (async, polling-based)

1. `POST /upload-video` validates the video MIME type, uploads the submission to GCS, writes an `evaluation_sessions/{id}` doc with `status="uploaded"`, and returns `201` with the session id.
2. `POST /analyze-video` (body: `{session_id, problem_statement?, solution_description?, criteria?}`) verifies ownership, flips the session to `processing`, and schedules `analyze_video_for_session` via FastAPI **`BackgroundTasks`**, returning `202`. The background task: (a) if a `problem_statement` + `solution_description` are supplied, first asks **Gemini** to generate a *"Product & Feature Validation Checklist"* (mirrors the `VideoAnalyzer.py` prototype's `generate_context` step); (b) sends the GCS video URI + checklist/rubric to Gemini (`client.models.generate_content`, `response_mime_type="application/json"`), parses the structured evaluation (scores + `checklist` + markdown `report`), and drives the session to `completed`/`failed`. Because it's in-process, analysis does not survive a restart — long analyses rely on the deployed Cloud Run `--timeout=3600`.
3. The frontend **polls** `GET /evaluations/{session_id}` for status; a completed session carries the `result` (per-criterion scores, checklist, report, strengths/improvements, verdict). Ownership is enforced: a session is only returned to its owner or an admin.

The Vertex client pattern is `genai.Client(vertexai=True, project=..., location=...)` with `GEMINI_MODEL` (default `gemini-2.5-flash`), matching the working `request.py` prototype. Criteria scores are `problem_coverage`, `solution_demonstration`, `technical_execution`, `presentation`, `impact` (each 0-10), plus an `overall_score` 0-100.

GCS object layout: `evaluations/{user_id}/{session_id}/submission.<ext>`. The evaluation service builds its own GCS client (reusing the Firebase service-account env vars) separate from the Firebase SDK, and passes the `gs://` URI directly to Gemini on Vertex AI (no re-download).

### Startup seeding

`DatabaseSeeder` (`app/utils/seeder.py`) runs in the `lifespan` startup and idempotently ensures a default **admin** (`admin@nxtwave.co.in`) and **test user** (`test@nxtwave.co.in`) exist in both Firebase Auth and Firestore (default password `12345678`). Seeding failures are logged but do **not** abort startup. Per project convention, do not add standalone seed scripts — extend this seeder.

## Configuration

All config is env-driven (`.env` locally, Cloud Run secrets/env in prod — see `.env.example`). Key vars:
- **Auth/Firestore:** `FIREBASE_PROJECT_ID`, `FIREBASE_PRIVATE_KEY`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_WEB_API_KEY` (required for login).
- **Evaluation:** `GOOGLE_CLOUD_PROJECT` (falls back to `FIREBASE_PROJECT_ID`), `GOOGLE_CLOUD_LOCATION`, `EVALUATION_BUCKET_NAME` (falls back to `VIDEO_BUCKET_NAME`), `GEMINI_MODEL` (default `gemini-2.5-flash`).

## Deployment

`cloudbuild.yaml` builds the image to Artifact Registry (`asia-south1`), ensures the `gs://$PROJECT_ID-hackathon-evaluations` bucket exists, and deploys to **Cloud Run** (`asia-south1`, `--allow-unauthenticated`, 1Gi/1cpu, 3600s timeout). Firebase secrets come from Secret Manager; non-secret config via `--set-env-vars`. The `Dockerfile` listens on `8080` (Cloud Run convention); local/compose use `8000`.
