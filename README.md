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

| Email                              | Role       | Approval   | Profile fields                          |
| ---------------------------------- | ---------- | ---------- | --------------------------------------- |
| `admin@nxtwave.co.in`              | admin      | —          | first/last name, employee ID, mobile    |
| `evaluator@nxtwave.co.in`          | evaluator  | approved   | first/last name, employee ID            |
| `evaluator.pending@nxtwave.co.in`   | evaluator  | pending    | first/last name, employee ID            |
| `student@nxtwave.co.in`            | student    | approved   | first/last name, NIAT ID, mobile        |

```bash
# Log in -> sets an HttpOnly `access_token` cookie (not returned in the body)
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{"email":"student@nxtwave.co.in","password":"12345678"}'
```

The session cookie is sent automatically on subsequent requests. From a browser/frontend, use `credentials: "include"` on `fetch` or axios `withCredentials: true`.

Log out with `POST /auth/logout` (clears the cookie).

For API clients and Swagger, the `Authorization: Bearer <token>` header is still supported as a fallback.

### Registration

**Student** (`POST /auth/register/student`):

```bash
curl -X POST http://localhost:8000/auth/register/student \
  -H "Content-Type: application/json" \
  -d '{
        "first_name": "John",
        "last_name": "Doe",
        "niat_id": "NIAT12345",
        "email": "john.doe@example.com",
        "mobile_no": "9876543210",
        "password": "12345678",
        "confirm_password": "12345678"
      }'
```

**Evaluator** (`POST /auth/register/evaluator`) — requires a `@nxtwave.co.in` email and starts with `approval_status: pending`:

```bash
curl -X POST http://localhost:8000/auth/register/evaluator \
  -H "Content-Type: application/json" \
  -d '{
        "first_name": "Jane",
        "last_name": "Smith",
        "employee_id": "EMP12345",
        "email": "jane.smith@nxtwave.co.in",
        "password": "12345678",
        "confirm_password": "12345678"
      }'
```

Pending evaluators can log in and call `GET /auth/me`, but other app routes return `403` until an admin approves them.

## Core endpoints

| Method | Path                              | Auth  | Description                                              |
| ------ | --------------------------------- | ----- | ------------------------------------------------------- |
| POST   | `/auth/register/student`          | —     | Student self-registration                               |
| POST   | `/auth/register/evaluator`        | —     | Evaluator self-registration (pending approval)          |
| POST   | `/auth/login`                     | —     | Log in; token stored in HttpOnly cookie                 |
| POST   | `/auth/logout`                    | —     | Clear session cookie                                    |
| GET    | `/auth/me`                        | user  | Current user profile (includes `approval_status`)       |
| POST   | `/submissions`                    | student | Upload video + project details (creates submission)     |
| GET    | `/submissions`                    | student | List the student's submissions                          |
| GET    | `/submissions/{id}`               | user    | Get submission status / evaluation result               |
| POST   | `/submissions/{id}/evaluate`      | student | Start AI evaluation (`evaluation_criteria` optional)    |
| GET    | `/admin/users`                    | admin | List non-admin users                                    |
| GET    | `/admin/evaluators/pending`       | admin | List evaluators awaiting approval                       |
| GET    | `/admin/evaluators`               | admin | List all evaluators                                     |
| POST   | `/admin/evaluators/{id}/approve`  | admin | Approve a pending evaluator                             |

### Student submission flow

```bash
# 1. Log in (sets HttpOnly cookie)
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{"email":"student@nxtwave.co.in","password":"12345678"}'

# 2. Create a submission (video + required project fields)
curl -X POST http://localhost:8000/submissions \
  -b cookies.txt \
  -F "video=@demo.webm;type=video/webm" \
  -F "title=Neura CDN" \
  -F "problem_statement=Building UI by hand is slow and inconsistent." \
  -F "solution_description=Auto-generates reusable HTML/CSS components via CDN."

# 3. Start AI evaluation (evaluation_criteria is optional)
curl -X POST http://localhost:8000/submissions/<submission_id>/evaluate \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{}'

# 4. Poll for the result
curl http://localhost:8000/submissions/<submission_id> \
  -b cookies.txt
# -> { "status": "completed",
#      "result": { "overall_score": 82, "criteria": {...},
#                  "checklist": "1. PROBLEM ESTABLISHMENT ...",
#                  "report": "## Analysis ...", ... } }
```

`problem_statement` / `solution_description` are optional — omit them to judge the
video against a generic hackathon rubric. You can also pass a freeform
`"criteria"` string to focus the evaluation.

## Production (cross-origin frontend)

When the Vercel frontend calls the Cloud Run API, HttpOnly cookie auth requires:

| Setting | Cloud Run value |
|---|---|
| `ENVIRONMENT` | `production` (sets `Secure` on cookies) |
| `COOKIE_SAMESITE` | `none` |
| `ALLOWED_ORIGINS` | Your frontend URL, e.g. `https://ai-hackathon-evaluator.vercel.app` |

These are set in `cloudbuild.yaml` for deploy. CORS uses `allow_credentials=True` with an explicit origin (never `*`).

The frontend must send requests with `credentials: "include"`.

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
│   └── submissions.py      # /submissions (student upload & evaluate)
├── services/
│   ├── firebase.py         # Firebase Admin singleton (Auth + Firestore)
│   ├── user_service.py     # user Firestore operations
│   └── submission_service.py # GCS upload + Gemini evaluation
└── utils/
    ├── seeder.py           # default admin + test user
    └── validators.py
```
