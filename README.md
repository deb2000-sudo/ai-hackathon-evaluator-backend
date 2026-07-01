# AI Hackathon Evaluator Backend

A FastAPI backend that lets participants upload their hackathon submission video and get an **AI evaluation** of it (per-criterion scores, strengths, improvements, and an overall verdict) powered by Vertex AI **Gemini**. Auth is handled by Firebase (same login system as the NxtCreate backend).

## Quick start

```bash
# 1. Create/activate a virtual environment (Python 3.11+)
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash

# 2. Install dependencies
pip install -e ".[dev]"        # or: pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env           # then fill in the values

# 4. Run
uvicorn app.main:app --reload  # http://localhost:8000/docs
```

## Authentication

Seeded users (created on startup, password `12345678`):

| Email                   | Role  |
| ----------------------- | ----- |
| `admin@nxtwave.co.in`   | admin |
| `test@nxtwave.co.in`    | user  |

```bash
# Log in -> returns an id_token
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@nxtwave.co.in","password":"12345678"}'
```

Use the returned `id_token` as `Authorization: Bearer <id_token>` on every protected route.

## Core endpoints

| Method | Path                       | Auth  | Description                                              |
| ------ | -------------------------- | ----- | ------------------------------------------------------- |
| POST   | `/auth/login`              | —     | Log in, get an `id_token`                               |
| GET    | `/auth/me`                 | user  | Current user profile                                    |
| POST   | `/upload-video`            | user  | Upload a submission video → creates an evaluation session |
| POST   | `/analyze-video`           | user  | Start AI evaluation for an uploaded session (background) |
| GET    | `/evaluations/{id}`        | user  | Poll status; returns the evaluation `result` when done  |
| GET    | `/admin/users`             | admin | List non-admin users                                    |

### Typical flow

```bash
TOKEN="<id_token>"

# 1. Upload a submission video
curl -X POST http://localhost:8000/upload-video \
  -H "Authorization: Bearer $TOKEN" \
  -F "video=@demo.mp4;type=video/mp4"
# -> { "id": "<session_id>", "status": "uploaded", ... }

# 2. Kick off analysis. Provide the problem + solution to have Gemini build a
#    "Product & Feature Validation Checklist" and judge the video against it.
curl -X POST http://localhost:8000/analyze-video \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "session_id":"<session_id>",
        "problem_statement":"Building UI components by hand is slow and inconsistent.",
        "solution_description":"Neura CDN auto-generates reusable HTML/CSS components and serves them via CDN."
      }'
# -> { "status": "processing", ... }

# 3. Poll for the result
curl http://localhost:8000/evaluations/<session_id> \
  -H "Authorization: Bearer $TOKEN"
# -> { "status": "completed",
#      "result": { "overall_score": 82, "criteria": {...},
#                  "checklist": "1. PROBLEM ESTABLISHMENT ...",
#                  "report": "## Analysis ...", ... } }
```

`problem_statement` / `solution_description` are optional — omit them to judge the
video against a generic hackathon rubric. You can also pass a freeform
`"criteria"` string to focus the evaluation.

## Configuration

See [.env.example](.env.example). Login needs the `FIREBASE_*` vars; video analysis additionally needs `GOOGLE_CLOUD_PROJECT`, `EVALUATION_BUCKET_NAME` (an existing GCS bucket), and `GEMINI_MODEL`.

## Project layout

```
app/
├── main.py                 # app factory, CORS, error handlers, lifespan seeding
├── middleware/
│   └── auth_middleware.py  # get_current_user / get_admin_user dependencies
├── models/
│   ├── user_model.py       # auth schemas
│   └── evaluation_model.py # upload / analyze / result schemas
├── routes/
│   ├── auth.py             # /auth
│   ├── admin.py            # /admin
│   └── evaluation.py       # /upload-video, /analyze-video, /evaluations/{id}
├── services/
│   ├── firebase.py         # Firebase Admin singleton (Auth + Firestore)
│   ├── user_service.py     # user Firestore operations
│   └── evaluation_service.py # GCS upload + Gemini evaluation
└── utils/
    ├── seeder.py           # default admin + test user
    └── validators.py
```
