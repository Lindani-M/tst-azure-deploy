import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { EventType, PublicClientApplication } from '@azure/msal-browser';
import { MsalProvider } from '@azure/msal-react';
import App from './App.jsx';
import { API_BASE, configureApi } from './api.js';
import './styles.css';

const root = createRoot(document.getElementById('root'));

// Shown straight away: the backend scales to zero when idle, so the first request can take a few seconds.
function Loading() {
  return (
    <main className="auth-screen">
      <section className="auth-card">
        <p className="subtitle">Loading…</p>
      </section>
    </main>
  );
}
root.render(<Loading />);

async function start() {
  // Client ID, authority and scope come from the backend, so only the backend URL is baked into the build.
  let res;
  try {
    res = await fetch(`${API_BASE}/api/config`, { signal: AbortSignal.timeout(45_000) });
  } catch {
    throw new Error('The server is taking too long to respond. Please refresh the page in a moment.');
  }
  if (!res.ok) throw new Error(`Could not load sign-in settings (${res.status}). Please refresh the page in a moment.`);
  const config = await res.json();

  const msal = new PublicClientApplication({
    auth: {
      clientId: config.clientId,
      authority: config.authority, // https://<subdomain>.ciamlogin.com/
      redirectUri: `${window.location.origin}/redirect.html`, // MSAL v5 redirect bridge page
      postLogoutRedirectUri: `${window.location.origin}/`,
    },
    cache: { cacheLocation: 'sessionStorage' },
  });

  await msal.initialize();

  // Finishes a sign-in/sign-up that just came back from the Entra hosted page.
  const result = await msal.handleRedirectPromise();
  if (result?.account) {
    msal.setActiveAccount(result.account);
  } else if (!msal.getActiveAccount() && msal.getAllAccounts().length > 0) {
    msal.setActiveAccount(msal.getAllAccounts()[0]);
  }

  msal.addEventCallback((event) => {
    // In MSAL v5 the LOGIN_SUCCESS payload is the AccountInfo.
    if (event.eventType === EventType.LOGIN_SUCCESS && event.payload) {
      msal.setActiveAccount(event.payload);
    }
  });

  configureApi(msal, config.scopes);

  root.render(
    <StrictMode>
      <MsalProvider instance={msal}>
        <App scopes={config.scopes} />
      </MsalProvider>
    </StrictMode>,
  );
}

start().catch((err) => {
  console.error(err);
  root.render(
    <main className="auth-screen">
      <section className="auth-card">
        <h1>Notes</h1>
        <p className="error">{err.errorCode || err.message}</p>
      </section>
    </main>,
  );
});
