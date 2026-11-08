"""
Cosmos DB access with Entra ID (no account keys).

DefaultAzureCredential picks up AZURE_TENANT_ID + AZURE_CLIENT_ID + AZURE_CLIENT_SECRET: the
Default Directory service principal that holds the "Cosmos DB Built-in Data Contributor" role.
Locally these come from the project-root .env; on the Container App from its env vars (the secret
via secretref). The client is created on first use so a missing setting gives a clear error.

Containers (created once in Data Explorer; the data role can't create them):
  users  partition key /id      id     = Entra object ID   (app profile)
  notes  partition key /userId  userId = Entra object ID
"""
import os
import threading

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

_containers = None
_lock = threading.Lock()


def _get():
    global _containers
    with _lock:
        if _containers is None:
            endpoint = os.getenv("COSMOS_ENDPOINT")
            if not endpoint:
                raise RuntimeError("COSMOS_ENDPOINT is not set (see docs/SETUP.md).")
            database_id = os.getenv("COSMOS_DATABASE", "tst-db")
            client = CosmosClient(endpoint, credential=DefaultAzureCredential(), connection_timeout=10)
            database = client.get_database_client(database_id)
            _containers = {
                "endpoint": endpoint,
                "database": database_id,
                "users": database.get_container_client("users"),
                "notes": database.get_container_client("notes"),
            }
        return _containers


def users():
    return _get()["users"]


def notes():
    return _get()["notes"]


def check() -> dict:
    """Health check: can we reach both containers with our identity?"""
    c = _get()
    c["users"].read()
    c["notes"].read()
    return {"endpoint": c["endpoint"], "database": c["database"]}
