import { InteractionRequiredAuthError } from '@azure/msal-browser';

// Backend origin. Production: the Container App URL (set by the deploy workflow at build time;
// public, not a secret). Local dev: unset, so calls stay relative and the Vite proxy forwards them.
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');

let msal;
let scopes = [];

export function configureApi(instance, apiScopes) {
  msal = instance;
  scopes = apiScopes;
}

// Gets an access token for our API from MSAL's cache, renewing it if needed.
async function getAccessToken() {
  const account = msal?.getActiveAccount();
  if (!account) return null;
  try {
    const result = await msal.acquireTokenSilent({ scopes, account });
    return result.accessToken;
  } catch (err) {
    if (err instanceof InteractionRequiredAuthError) {
      // The session at Entra has expired: send the user back to sign in.
      await msal.acquireTokenRedirect({ scopes, account });
      return new Promise(() => {}); // the page is navigating away
    }
    throw err;
  }
}

export async function api(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (auth) {
    const token = await getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}/api${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.error || `Request failed (${res.status})`);
    error.status = res.status;
    error.hint = data.hint;
    throw error;
  }
  return data;
}
