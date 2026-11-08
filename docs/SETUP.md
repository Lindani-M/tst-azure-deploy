# Setup guide: Notes app with Entra External ID and Cosmos DB

This guide covers every setup step for this project, in the order we did it on 8 November 2026. It includes the mistakes we hit and how to fix them. Follow it to rebuild the setup from scratch or to set up a new environment.

**What you end up with:** customers sign up with an email and password on a Microsoft-hosted page. Their accounts are stored in an Entra **external tenant**. The app keeps each user's notes in Cosmos DB, filed under their Entra user ID.

```
Browser (localhost:5243)                     Entra External ID (tstcustomers.ciamlogin.com)
  "Create account" ──── redirect ──────────▶ hosted sign-up page: email → code → password
  /redirect.html  ◀──── redirect ─────────── account created in the external tenant
  app gets an access token (MSAL)
  GET /api/notes  + Bearer token ──────────▶ FastAPI backend (Container App) checks signature, issuer, audience and scope
                                             └──▶ Cosmos DB (service principal)
```

## Two tenants: don't mix them up

| | Tenant | Holds | Used by | `.env` variables |
|---|---|---|---|---|
| **You** | Default Directory (existing) | Your admin account, the Azure subscription, Cosmos DB, the service principal | API → Cosmos DB | `AZURE_*` |
| **Customers** | `tst-customers` (new, external) | Customer accounts, user flow, app registration, branding | Sign-up and sign-in | `ENTRA_*` |

Before each step in parts 2 and 3, check which directory the top-right corner of the portal shows.

## Our values (none of these are secrets)

| Item | Value |
|---|---|
| Resource group | `ai-300-rg` |
| Cosmos DB account | `tst-cosmos-db` (South Africa North) |
| Cosmos database / containers | `tst-db` / `users`, `notes` |
| External tenant | `tst-customers`, domain `tstcustomers.onmicrosoft.com` |
| External tenant ID | `8cc59ab2-a767-4059-b8e7-4ba0a455907a` |
| App registration | `tst-notes-web`, client ID `831c423f-b978-4f7d-9fb2-e541dadedccd` |
| API scope | `api://831c423f-b978-4f7d-9fb2-e541dadedccd/access_as_user` |
| User flow | `SignUpSignIn` |

The service principal's **client secret** is the only secret in this setup. It lives only in `.env`, which git ignores. Never put it in a document or commit.

---

## Part 1: Cosmos DB (Azure portal, Default Directory)

### 1.1 Create the account
Azure portal → **Create Azure Cosmos DB account** → **Azure Cosmos DB for NoSQL**:

| Setting | Value | Why |
|---|---|---|
| Resource group | `ai-300-rg` | |
| Account name | `tst-cosmos-db` | |
| Availability zones | Disable | Can't be changed later. Not needed for a test |
| Location | (Africa) South Africa North | Keeps data in South Africa (POPIA) |
| Capacity mode | Provisioned throughput | Required for the free tier |
| Apply free tier discount | **Apply** | First 1000 RU/s and 25 GB free. Only one free-tier account per subscription, and it **can't be turned on later** |
| Limit total account throughput | Ticked | Caps the account at 1000 RU/s, so it can't go over the free tier |

### 1.2 Create the database and containers
Cosmos account → **Data Explorer** → **New Container**. Do this twice:

| Database | Container id | Partition key | Throughput |
|---|---|---|---|
| `tst-db` (Create new the first time, then Use existing) | `users` | `/id` | **Manual, 400 RU/s** |
| `tst-db` (Use existing) | `notes` | `/userId` | **Manual, 400 RU/s** |

- **Container names:** they must be exactly `users` and `notes`, because the code expects them.
- **Why Manual 400:** 2 × 400 = 800 RU/s, which is within the free 1000. The default Autoscale (maximum 1000) would count each container as up to 1000 RU/s, which goes over the free tier and the account limit.
- **Why create them here:** the app's role (step 1.3) can read and write data but can't create databases or containers.

### 1.3 Give the service principal access to the data
Run this in **Cloud Shell (PowerShell)**:

```powershell
$rg = "ai-300-rg"; $account = "tst-cosmos-db"
$clientId = "<service principal client ID>"

# The role assignment needs the service principal's OBJECT ID, not its client ID
$spObjectId = az ad sp show --id $clientId --query id -o tsv

# Cosmos DB Built-in Data Contributor
az cosmosdb sql role assignment create `
  --account-name $account --resource-group $rg `
  --role-definition-id 00000000-0000-0000-0000-000000000002 `
  --principal-id $spObjectId --scope "/"
```

- **Not in the IAM blade:** this is a Cosmos **data** role. It doesn't appear under the account's **Access control (IAM)** blade, so you have to assign it with the command.
- **Scope `/`:** covers the whole account.
- **Check it:** `az cosmosdb sql role assignment list --account-name $account --resource-group $rg -o table`
- **Timing:** it can take a few minutes to take effect.

---

## Part 2: The external tenant (Entra admin center, https://entra.microsoft.com)

Use the **Entra admin center**, not the Azure portal, for every step from here on. Both show the same data, but the Azure portal tends to open in your Default Directory.

### 2.1 Create the external tenant
**Entra ID → Overview → Manage tenants → Create** → choose **External** → Continue.

| Setting | Value |
|---|---|
| Tenant name | `tst-customers` |
| Domain name | `tstcustomers`, which becomes the **subdomain** in `tstcustomers.ciamlogin.com` |
| Country/Region | South Africa. **This can't be changed later.** It decides where customer data is stored |
| Subscription / Resource group | Azure subscription 1 / `ai-300-rg` |

**Review + create** → **Create**. It takes a few minutes, and can take up to 30.

### 2.2 Switch into the tenant
Gear icon → **Directories + subscriptions** → **tst-customers**. The top right should now show **TST-CUSTOMERS**. Do every remaining step in Part 2 inside this tenant.

Copy the **Tenant ID** from **Entra ID → Overview**. It goes into `ENTRA_TENANT_ID`.

### 2.3 Create the user flow
**External Identities → User flows → + New user flow** (or the **User flows** card on the overview page):

| Setting | Value |
|---|---|
| Name | `SignUpSignIn` (can't be renamed later) |
| Identity providers | Tick **Email Accounts**, then choose **Email with password** |
| User attributes | Tick **Display Name** |

Click **Create**.

**Email with password vs Email one-time passcode:** they're radio buttons, so you pick one. **Email with password** still emails a verification code during sign-up, to prove the user owns the address. After that, users sign in with their email and password.

### 2.4 Register the app
**App registrations → + New registration**:

| Setting | Value |
|---|---|
| Name | `tst-notes-web` |
| Supported account types | Single tenant only - tst-customers |
| Redirect URI, platform | **Single-page application (SPA)**, not Web |
| Redirect URI, URL | `http://localhost:5243/redirect.html`, typed exactly |

Click **Register**. Copy the **Application (client) ID** from the Overview page. It goes into `ENTRA_CLIENT_ID`.

- **Why `/redirect.html`:** MSAL v5 returns users from Entra to a small separate "bridge" page, [frontend/redirect.html](../frontend/redirect.html), not to the app itself.
- **Watch for typos:** we first registered `redirect.htm`, missing the final **l**. That caused error `AADSTS50011` at the end of sign-up.

### 2.5 Add the sign-out return URL
In the app: **Authentication (Preview)** → under **Single-page application**, add a second URI, `http://localhost:5243/` → **Save**.

The list should now contain exactly these two:
```
http://localhost:5243/redirect.html
http://localhost:5243/
```

### 2.6 Expose an API
In the app: **Expose an API**.

1. Next to **Application ID URI**, click **Add**. Keep the default, `api://<client-id>`, and click **Save**.
2. **+ Add a scope**:

| Field | Value |
|---|---|
| Scope name | `access_as_user` (exactly this; the API checks for it) |
| Who can consent? | **Admins only** |
| Admin consent display name | `Access Notes API` |
| Admin consent description | `Allows the app to call the Notes API as the signed-in user.` |
| State | Enabled |

Click **Add scope**.

The frontend and the API share this **one** app registration: the frontend requests a token for its own exposed scope.

### 2.7 API permissions and admin consent
In the app: **API permissions**.

1. **+ Add a permission** → **APIs my organization uses** → `tst-notes-web` → **Delegated permissions** → tick `access_as_user` → **Add permissions**.
2. Click **Grant admin consent for tst-customers** → **Yes**.

Both `User.Read` and `access_as_user` should then show **Granted for tst-customers**. In external tenants customers can't approve permissions themselves, so this step is required.

### 2.8 Check the token version
In the app: **Manifest**. Under `"api"`, `"requestedAccessTokenVersion"` should be `2`. Ours was already `2` for a new app in an external tenant. If it's `null`, set it to `2` and click **Save**.

### 2.9 Add the email claim
In the app: **Token configuration** → **+ Add optional claim** → token type **Access** → tick **email** → **Add**. If it asks to turn on the Microsoft Graph email permission, accept.

- **Why it's needed:** without it, the API never receives the user's real email. `preferred_username` isn't reliable: for customer accounts it can be the internal `<guid>@tstcustomers.onmicrosoft.com` name.
- **Email is never used to identify users:** data is always filed under the Entra user ID (`oid`).

### 2.10 Link the app to the user flow
**External Identities → User flows → SignUpSignIn → Applications → + Add application** → tick `tst-notes-web` → **Select**.

Without this, there's no sign-up page for the app to send users to. An app can belong to only one user flow.

### 2.11 Company branding (optional, but makes the hosted page match the app)
Overview page → **Company branding** card → **Default sign-in** → **Edit**:

| Tab | Setting | Value |
|---|---|---|
| Basics | Favicon | [branding/favicon-32.png](../branding/favicon-32.png) |
| Basics | Page background colour | `#F5F3FF` (soft lavender). Skip the background image, because Entra darkens it |
| Sign-in form | Banner logo | [branding/banner-logo-245x36.png](../branding/banner-logo-245x36.png) |
| Sign-in form | Square logo (light and dark) | [branding/square-logo-240.png](../branding/square-logo-240.png) |
| Sign-in form | Username hint text | `Email address` |
| Sign-in form | Sign-in page text | `Welcome to Notes. Sign in or create an account to get started.` |

**Review + create** → **Create**. It can take a few minutes to appear.

---

## Part 3: Configure and run the app

### 3.1 `.env` (repo root, never committed)
```
# Cosmos DB + the service principal that reads/writes it (Default Directory)
COSMOS_ENDPOINT=https://tst-cosmos-db.documents.azure.com:443/
COSMOS_DATABASE=tst-db
AZURE_TENANT_ID=<Default Directory tenant ID>
AZURE_CLIENT_ID=<service principal client ID>
AZURE_CLIENT_SECRET=<service principal secret>

# Entra External ID (tst-customers). None of these are secrets.
ENTRA_TENANT_SUBDOMAIN=tstcustomers
ENTRA_TENANT_ID=8cc59ab2-a767-4059-b8e7-4ba0a455907a
ENTRA_CLIENT_ID=831c423f-b978-4f7d-9fb2-e541dadedccd
```

### 3.2 Run (two terminals)
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

### 3.3 Check it works
1. Click **Create account**. You go to `tstcustomers.ciamlogin.com`, which shows the Notes logo if you did step 2.11.
2. Enter your email, then the code from the email, then a password and display name.
3. You come back to the app showing your name and email in the top bar.
4. Add a note.
5. **Entra → tst-customers → Users:** the new customer account is listed.
6. **Cosmos → Data Explorer → tst-db:** `users` has an item whose `id` is your Entra user ID and whose `email` is your real email. `notes` holds your note.

---

## Problems we hit, and fixes

| Symptom | Cause | Fix |
|---|---|---|
| `endpoints_resolution_error` on the app's sign-in screen | The tenant's issuer is ID-based (`https://<tenantId>.ciamlogin.com/<tenantId>/v2.0`). MSAL v5 rejects it if the authority is only `https://tstcustomers.ciamlogin.com/` | The authority must include the tenant ID: `https://tstcustomers.ciamlogin.com/<tenantId>/`. [backend/auth.py](../backend/auth.py) builds it from `.env` |
| `AADSTS50011` "redirect URI … does not match" after entering the password | The registered URI was `redirect.htm` | Fix it to exactly `http://localhost:5243/redirect.html` (SPA platform). The account had already been created, so use **Sign in** afterwards |
| Top bar showed `<guid>@tstcustomers.onmicrosoft.com` instead of the email | The API used `preferred_username` when there was no `email` claim | Add the email optional claim (step 2.9). The code now ignores `preferred_username` and won't overwrite a saved email |
| Entra's "Pick an account" screen shows `<guid>@tstcustomers.onmicrosoft.com` | That's the account's internal username. We didn't find a setting that changes what Entra's own page shows | Expected. Pick the account, or **⋮ → Forget** it |
| Cosmos 403 | Data role missing or not yet active, or the firewall is blocking your IP | Step 1.3, then wait a few minutes |
| Sign-in page says the app isn't linked to a flow | Step 2.10 skipped | Link the app to `SignUpSignIn` |

---

## Part 4: Deploy: backend to Container Apps, frontend to Static Web Apps

This follows the same pattern as `aggp-credit-card-recon`. The backend and frontend are deployed separately, and the frontend calls the backend **directly**:

```
Browser ──► Static Web App  (https://lemon-cliff-0b2596c0f.3.azurestaticapps.net)   React build only
   │
   └─ fetch https://<container-app-fqdn>/api/...   + Authorization: Bearer <Entra token>
        ▼
      Container App (FastAPI, port 8000)   CORS allows only the Static Web App origin
        ▼  service principal (AZURE_CLIENT_SECRET = secretref:cosmos-sp-secret)
      Cosmos DB
```

- **How the frontend finds the backend:** at deploy time the workflow looks up the Container App's address and builds React with `VITE_API_BASE_URL=https://<fqdn>`. That's public, not a secret. Locally it's left unset, so `/api` calls go through the Vite proxy.
- **Workflow:** [.github/workflows/deploy.yml](../.github/workflows/deploy.yml) runs two jobs, on a push to `main` that touches `backend/`, `frontend/`, the `Dockerfile` or the workflow, or by hand:
  - **deploy-backend:** log in to Azure → log in to ACR with the service principal → build and push the [Dockerfile](../Dockerfile) image → let the Container App pull from ACR → store the client secret as a Container App secret → set ingress to port 8000 → update the image and environment variables (0.25 vCPU, 0.5 GiB, scales to zero).
  - **deploy-frontend:** `npm ci` → look up the Container App address → `npm run build` with `VITE_API_BASE_URL` → upload `frontend/dist` with the deployment token.
- **One service principal** (Default Directory) does everything: deploying (Contributor on the Container App and its environment, AcrPush on ACR), and reading and writing Cosmos (data role, step 1.3).

### 4.1 Create the resources (Azure portal, Default Directory, `ai-300-rg`)
1. **Container Registry:** SKU **Basic**. Note its **login server**, e.g. `<name>.azurecr.io`.
2. **Container Apps environment:** **Consumption** plan. For POPIA, choose **South Africa North** if it's offered, so processing stays in the same country as the data.
3. **Container App** in that environment:
   - Image: keep the **quickstart image** for now. The workflow replaces it.
   - Ingress: **Enabled**, accepting traffic from **anywhere**. The workflow sets the target port to 8000.

### 4.2 Give the service principal access to the deployment resources
Cloud Shell (PowerShell). Fill in your resource names:
```powershell
$sp  = "<service principal client ID>"
$rg  = "ai-300-rg"
$app = "<container app name>"; $env = "<container apps environment name>"; $acr = "<registry name>"

az role assignment create --assignee $sp --role Contributor --scope (az containerapp show     -n $app -g $rg --query id -o tsv)
az role assignment create --assignee $sp --role Contributor --scope (az containerapp env show -n $env -g $rg --query id -o tsv)
az role assignment create --assignee $sp --role AcrPush     --scope (az acr show              -n $acr -g $rg --query id -o tsv)
```
That's **Contributor** on the Container App and its environment, and **AcrPush** on the registry. AcrPush covers both pushing the image and the Container App pulling it with the same credentials. These were granted on 8 November 2026.

### 4.3 Add the production redirect URIs in Entra
**tst-customers** → App registrations → `tst-notes-web` → **Authentication (Preview)** → under **Single-page application**, add:
```
https://lemon-cliff-0b2596c0f.3.azurestaticapps.net/redirect.html
https://lemon-cliff-0b2596c0f.3.azurestaticapps.net/
```
Keep the two `localhost` URIs, so local dev keeps working.

### 4.4 Set the GitHub secrets
This works the same way as in the recon project. **`set-secrets.sh`** in the repo root is **git-ignored**, because it holds real values. Never commit it.

1. Open `set-secrets.sh` and fill in the placeholders at the top:
   - the Default Directory tenant ID
   - the client secret
   - the Container App name
   - the ACR login server
   - the Static Web App deployment token (Static Web App → Overview → *Manage deployment token*)
2. In Git Bash, from the repo root, after `gh auth login`, run:
   ```bash
   bash set-secrets.sh
   ```
3. Afterwards, clear the secret values from the file or delete it. GitHub keeps the secrets.

| GitHub secret | What |
|---|---|
| `CLIENT_ID`, `CLIENT_SECRET`, `TENANT_ID` | The Default Directory service principal |
| `AZURE_CREDENTIALS` | The same three values plus the subscription ID, as JSON for `azure/login` |
| `RESOURCE_GROUP`, `CONTAINER_APP`, `ACR_LOGIN_SERVER` | The resources from 4.1 |
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | The Static Web App deployment token |

The workflow sets the non-secret runtime values directly: the Cosmos endpoint and database, the `ENTRA_*` values, and `ALLOWED_ORIGINS`, which is the Static Web App URL. If any of them change, edit them in `deploy.yml`.

### 4.5 Check Cosmos networking
Cosmos `tst-cosmos-db` → **Networking**: public access must allow **All networks**. Otherwise the Container App's outgoing IP addresses would have to be allow-listed, and on the Consumption plan those can change.

### 4.6 Deploy
Push to `main`, or go to GitHub → **Actions** → *Deploy* → **Run workflow**. Both jobs should go green.

### 4.7 Check it
1. `https://<container-app-fqdn>/api/health` should return `"cosmos":"ok"`. The first request after an idle period takes a few seconds while the app starts from zero.
2. Open `https://lemon-cliff-0b2596c0f.3.azurestaticapps.net`, **Sign in**, and add a note.
3. If something fails, read the backend logs with `az containerapp logs show -n <container app> -g ai-300-rg --follow`.

| Symptom | Likely cause |
|---|---|
| Browser console shows a **CORS** error | `ALLOWED_ORIGINS` in `deploy.yml` doesn't exactly match the Static Web App URL: `https`, no trailing slash |
| `Could not load sign-in settings from …/api/config` | The backend isn't running or deployed, or the frontend was built before the Container App existed. Re-run the workflow |
| 401 after signing in | The logs show `Token rejected: …` with the exact reason |
| `azure/login` fails with "No subscriptions found" | The service principal has no role it can see in the subscription. Check 4.2 |

### Cost
For under 100 daily users, roughly **$5–6/month**: ACR Basic is about $5, and Container App compute is about $0–1 when it scales to zero. The Static Web App (Free), Cosmos (free tier) and Entra (under 50,000 monthly users) cost $0. For no cold starts, use `--min-replicas 1` in the workflow, which adds about $4–6/month at this size.

---

## Not done yet

- **Forgot password:** probably needs **Email one-time passcode** turned on for the whole tenant (Authentication methods). Not yet confirmed or tested.
- **Managed identity:** Container Apps support it, so the Cosmos client secret could later be replaced by the app's managed identity. That's not set up yet, to match the recon project's single-service-principal setup.
- **Commit and push:** this triggers the first deployment. `.env` is in `.gitignore`. The image only ever contains `backend/`, per `.dockerignore`.
