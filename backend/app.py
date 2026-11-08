"""
Notes API (FastAPI). Deployed as an Azure Container App; the React SPA on Azure Static Web Apps
calls it directly with an Entra External ID bearer token (CORS allowlist, no cookies).

Run locally (reads the project-root .env):
    cd backend
    python -m uvicorn app:app --port 8000 --reload
"""
import logging
import os
import uuid
from datetime import datetime, timezone

from azure.core.exceptions import ClientAuthenticationError
from azure.cosmos import exceptions as cosmos_errors
from azure.identity import CredentialUnavailableError
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import auth
import db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# The Azure SDKs log every HTTP request with full headers at INFO; only show their warnings and errors.
logging.getLogger("azure").setLevel(logging.WARNING)
log = logging.getLogger("app")

# APP_ENVIRONMENT=production (set by the deploy workflow) hides internal error details from responses.
IS_PRODUCTION = os.getenv("APP_ENVIRONMENT", "").lower() == "production"
MAX_NOTE_LENGTH = 500

app = FastAPI(title="Notes API", docs_url=None, redoc_url=None, openapi_url=None)


# Catch-all for unexpected errors. Registered BEFORE the CORS middleware so it runs inside it:
# a 500 then still carries CORS headers and the browser shows the real message, not a "CORS error".
@app.middleware("http")
async def _unhandled_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        log.error("%s %s failed: %s: %s", request.method, request.url.path, type(exc).__name__, exc)
        body = {"error": "Something went wrong."}
        if not IS_PRODUCTION:
            body["hint"] = cosmos_hint(exc)
        return JSONResponse(body, status_code=500)


# The SPA sends an Entra bearer token on each call, so the backend is stateless (no cookies).
# CORS is a strict allowlist: the Static Web App origin in prod, localhost in dev.
# Authorization must be listed explicitly; a "*" wildcard does NOT cover it per the CORS spec.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5243").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
    max_age=600,
)


# ---------- errors: always {"error": "..."} so the SPA can show a message ----------

def cosmos_hint(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status == 403:
        return ("Cosmos returned 403. Check the service principal has the Cosmos DB Built-in Data Contributor "
                "role, and that the account firewall allows this caller.")
    if status == 404:
        return "Database or container not found. Check COSMOS_DATABASE and that containers users (/id) and notes (/userId) exist."
    if isinstance(exc, (CredentialUnavailableError, ClientAuthenticationError)):
        return "Could not get an Entra ID token for Cosmos. Check AZURE_TENANT_ID, AZURE_CLIENT_ID and AZURE_CLIENT_SECRET."
    return str(exc)


@app.exception_handler(auth.AuthError)
async def _auth_error(request: Request, exc: auth.AuthError):
    return JSONResponse({"error": exc.message}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse({"error": "Invalid request body."}, status_code=400)


def current_user(authorization: str | None = Header(default=None)) -> dict:
    return auth.authenticate(authorization)


# ---------- routes ----------

@app.get("/api/config")
def config():
    """Public sign-in settings for the SPA (client ID, authority, scope). Not secrets."""
    return auth.public_config()


@app.get("/api/health")
def health():
    try:
        return {"api": "ok", "cosmos": "ok", **db.check()}
    except Exception as exc:
        log.error("Cosmos health check failed: %s", exc)
        return JSONResponse({"api": "ok", "cosmos": "error", "hint": cosmos_hint(exc)}, status_code=503)


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    """The account lives in Entra; Cosmos keeps an app profile keyed by the Entra object ID."""
    try:
        existing = db.users().read_item(item=user["id"], partition_key=user["id"])
    except cosmos_errors.CosmosResourceNotFoundError:
        existing = {}
    now = datetime.now(timezone.utc).isoformat()

    profile = {
        "id": user["id"],
        # Keep the last real email seen; a token without one never overwrites it.
        "email": user["email"] or (existing.get("email") if auth.is_real_email(existing.get("email")) else None),
        "name": user["name"] or existing.get("name"),
        "firstSeen": existing.get("firstSeen") or now,
        "lastSeen": now,
    }
    db.users().upsert_item(profile)
    return {"email": profile["email"], "name": profile["name"], "firstSeen": profile["firstSeen"]}


@app.get("/api/notes")
def list_notes(user: dict = Depends(current_user)):
    # Scoped to the signed-in user's partition, so users only ever see their own notes.
    return list(db.notes().query_items(
        query="SELECT c.id, c.text, c.createdAt FROM c WHERE c.userId = @uid ORDER BY c.createdAt DESC",
        parameters=[{"name": "@uid", "value": user["id"]}],
        partition_key=user["id"],
    ))


class NoteIn(BaseModel):
    text: str


@app.post("/api/notes", status_code=201)
def create_note(note: NoteIn, user: dict = Depends(current_user)):
    text = note.text.strip()
    if not text or len(text) > MAX_NOTE_LENGTH:
        return JSONResponse({"error": f"A note must be 1 to {MAX_NOTE_LENGTH} characters."}, status_code=400)

    item = {
        "id": str(uuid.uuid4()),
        "userId": user["id"],
        "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    db.notes().create_item(item)
    return {"id": item["id"], "text": item["text"], "createdAt": item["createdAt"]}


@app.delete("/api/notes/{note_id}", status_code=204)
def delete_note(note_id: str, user: dict = Depends(current_user)):
    try:
        db.notes().delete_item(item=note_id, partition_key=user["id"])
    except cosmos_errors.CosmosResourceNotFoundError:
        return JSONResponse({"error": "Note not found."}, status_code=404)
    return Response(status_code=204)
