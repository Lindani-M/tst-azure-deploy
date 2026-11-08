# tst-azure-deploy

A small Notes app for learning real customer sign-up on Azure, end to end.

- **Sign-up and sign-in:** Microsoft Entra External ID (tenant `tst-customers`). Customers sign up with an email and password on a Microsoft-hosted page. Their accounts live in Entra, not in this app.
- **Frontend:** React + Vite + MSAL in [`frontend/`](frontend/). Deployed to **Azure Static Web Apps**.
- **Backend:** Python FastAPI in [`backend/`](backend/). Deployed as an **Azure Container App** from the root [`Dockerfile`](Dockerfile). It checks the Entra token on every request, and CORS allows only the Static Web App.
- **Data:** Azure Cosmos DB (`tst-cosmos-db`, South Africa North). The backend signs in to Cosmos with a service principal through Entra ID, so it uses no account keys. Notes are stored under each user's Entra ID.

**Full setup** (Cosmos, the external tenant, the app registration, branding, local run, deployment, the problems we hit and fixes): [`docs/SETUP.md`](docs/SETUP.md).

## Run locally

**Prerequisites:** Python 3.11+, Node.js 22+, and a project-root `.env` (variables in [`docs/SETUP.md`](docs/SETUP.md), step 3.1; never commit it).

**Backend** (FastAPI, port 8000). It reads the project-root `.env`:
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate     # Windows (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
python -m uvicorn app:app --port 8000 --reload
```

**Frontend** (React + Vite, port 5243). It forwards `/api` to the backend:
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5243.

## Deploy

[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) runs on push to `main`:
- **Backend:** builds the Docker image, pushes it to ACR, and updates the Container App.
- **Frontend:** builds React with the Container App's URL and uploads it to the Static Web App with the deployment token.

The GitHub secrets are set by `set-secrets.sh`. It's git-ignored because it holds real values, so never commit it. See [`docs/SETUP.md`](docs/SETUP.md), Part 4.
