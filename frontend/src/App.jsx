import { useEffect, useState } from 'react';
import { InteractionStatus } from '@azure/msal-browser';
import { useIsAuthenticated, useMsal } from '@azure/msal-react';
import { api } from './api.js';

export default function App({ scopes }) {
  const isAuthenticated = useIsAuthenticated();
  return (
    <>
      {/* Soft colour blobs behind the white page */}
      <div className="backdrop" aria-hidden="true">
        <span className="blob blob-1" />
        <span className="blob blob-2" />
        <span className="blob blob-3" />
      </div>
      {isAuthenticated ? <SignedIn /> : <SignIn scopes={scopes} />}
    </>
  );
}

const NOTE_COLOURS = ['violet', 'sky', 'mint', 'amber', 'rose'];

function isRealEmail(value) {
  return typeof value === 'string' && value.includes('@') && !value.toLowerCase().endsWith('.onmicrosoft.com');
}

function Logo() {
  return (
    <div className="logo" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
        <path d="M14 3v5h5" />
        <path d="M9 13h6M9 17h4" />
      </svg>
    </div>
  );
}

function SignIn({ scopes }) {
  const { instance, inProgress } = useMsal();
  const [error, setError] = useState('');
  const busy = inProgress !== InteractionStatus.None;

  // Both buttons go to the Microsoft-hosted page for the external tenant.
  // prompt: 'create' opens it directly on the sign-up screen.
  async function start(prompt) {
    setError('');
    try {
      // MSAL turns a leftover "active account" into a login hint, and Entra then pre-fills the
      // customer's internal <guid>@<tenant>.onmicrosoft.com username instead of their email.
      // Nobody is signed in on this screen, so clear it and let the user type their email.
      instance.setActiveAccount(null);
      await instance.loginRedirect({ scopes, ...(prompt ? { prompt } : {}) });
    } catch (err) {
      setError(err.errorCode || err.message);
    }
  }

  return (
    <main className="auth-screen">
      <section className="auth-card">
        <Logo />
        <h1>Welcome to Notes</h1>
        <p className="subtitle">Sign in to see your notes, or create a free account to get started.</p>

        <div className="auth-actions">
          <button className="btn btn-primary" onClick={() => start()} disabled={busy}>
            {busy ? 'Redirecting…' : 'Sign in'}
          </button>
          <button className="btn btn-outline" onClick={() => start('create')} disabled={busy}>
            Create account
          </button>
        </div>

        {error && <p className="error">{error}</p>}
      </section>
    </main>
  );
}

function SignedIn() {
  const { instance, accounts } = useMsal();
  const account = instance.getActiveAccount() ?? accounts[0];
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api('/me')
      .then(setProfile)
      .catch((err) => setError(err.hint ? `${err.message} ${err.hint}` : err.message));
  }, []);

  // For display only. account.username can be the internal <guid>@<tenant>.onmicrosoft.com name, so it isn't used;
  // the ID token's email claim (MSAL requests the "email" scope) is a display fallback, never trusted by the API.
  const idTokenEmail = account?.idTokenClaims?.email;
  const email = profile?.email || (isRealEmail(idTokenEmail) ? idTokenEmail : '');
  const name = profile?.name || account?.name || email || 'Account';
  const initial = (name.trim()[0] || '?').toUpperCase();

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Logo />
          <span>Notes</span>
        </div>
        <div className="user">
          <span className="avatar" aria-hidden="true">{initial}</span>
          <span className="user-text">
            <strong>{name}</strong>
            {email && email !== name && <span className="muted">{email}</span>}
          </span>
          <button className="btn btn-ghost" onClick={() => instance.logoutRedirect({ account })}>
            Sign out
          </button>
        </div>
      </header>

      <main className="content">
        {error && <p className="error">{error}</p>}
        {profile && <Notes />}
      </main>
    </div>
  );
}

function Notes() {
  const [notes, setNotes] = useState([]);
  const [text, setText] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    api('/notes')
      .then(setNotes)
      .catch((err) => setError(err.message));
  }, []);

  async function add(e) {
    e.preventDefault();
    setError('');
    try {
      const note = await api('/notes', { method: 'POST', body: { text } });
      setNotes((prev) => [note, ...prev]);
      setText('');
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(id) {
    setError('');
    try {
      await api(`/notes/${encodeURIComponent(id)}`, { method: 'DELETE' });
      setNotes((prev) => prev.filter((n) => n.id !== id));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="card">
      <h2>Your notes</h2>
      <p className="muted small">Only you can see these.</p>
      <form onSubmit={add} className="row">
        <input
          placeholder="Write a note…"
          maxLength={500}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" className="btn btn-primary" disabled={!text.trim()}>
          Add
        </button>
      </form>
      {error && <p className="error">{error}</p>}
      {notes.length === 0 ? (
        <p className="empty">No notes yet. Write your first one above.</p>
      ) : (
        <ul className="notes">
          {notes.map((n, i) => (
            <li key={n.id} className={`note note-${NOTE_COLOURS[i % NOTE_COLOURS.length]}`}>
              <div>
                <p>{n.text}</p>
                <time className="muted small">{new Date(n.createdAt).toLocaleString()}</time>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => remove(n.id)} aria-label="Delete note">
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
