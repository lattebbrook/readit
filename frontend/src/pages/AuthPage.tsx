import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useApp } from '../lib/store';

type Mode = 'login' | 'register';

export function AuthPage({ mode: initialMode = 'login' }: { mode?: Mode }) {
  const { signIn, signUp, continueAsGuest, notify } = useApp();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [username, setUsername] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === 'login') await signIn(email, password);
      else await signUp(email, password, username);
      notify('Welcome to ReadIt.', 'success');
      navigate('/');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'That did not work.');
    } finally {
      setBusy(false);
    }
  };

  const guest = async () => {
    setBusy(true);
    try {
      await continueAsGuest(username);
      notify('You are browsing as a guest. Your history is saved on this device.', 'success');
      navigate('/');
    } catch {
      setError('Could not start a guest session.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ maxWidth: 420, margin: '30px auto' }}>
      <div className="card card-pad">
        <h1 style={{ fontSize: 22, margin: '0 0 4px' }}>
          {mode === 'login' ? 'Log in' : 'Sign up'}
        </h1>
        <p className="small muted" style={{ marginTop: 0 }}>
          Everyone else on ReadIt is generated. You are the only real one — unless someone
          else signs in too.
        </p>

        <form onSubmit={submit}>
          {mode === 'register' ? (
            <div className="field">
              <label htmlFor="auth-username">Username</label>
              <input
                id="auth-username"
                value={username}
                onChange={(event) => setUsername(event.target.value.replace(/[^A-Za-z0-9_-]/g, ''))}
                placeholder="what people will call you"
                maxLength={20}
                required
              />
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              required
            />
          </div>

          <div className="field">
            <label htmlFor="auth-password">Password</label>
            <input
              id="auth-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="at least 6 characters"
              required
            />
          </div>

          {error ? (
            <p className="small" style={{ color: 'var(--danger)' }}>
              {error}
            </p>
          ) : null}

          <button className="btn btn-primary" style={{ width: '100%' }} disabled={busy} type="submit">
            {busy ? 'Working…' : mode === 'login' ? 'Log in' : 'Create account'}
          </button>
        </form>

        <div className="divider" />

        <button className="btn btn-outline" style={{ width: '100%' }} disabled={busy} onClick={() => void guest()}>
          Continue as guest
        </button>
        <p className="tiny faint center" style={{ marginTop: 8 }}>
          Guests can post, vote and create boards. You can attach an email later without losing
          anything.
        </p>

        <p className="small center" style={{ marginTop: 14 }}>
          {mode === 'login' ? (
            <>
              New here?{' '}
              <button className="btn-ghost" style={{ color: 'var(--link)' }} onClick={() => setMode('register')}>
                Sign up
              </button>
            </>
          ) : (
            <>
              Already have an account?{' '}
              <button className="btn-ghost" style={{ color: 'var(--link)' }} onClick={() => setMode('login')}>
                Log in
              </button>
            </>
          )}
        </p>
        <p className="tiny faint center">
          <Link to="/">Keep browsing without an account →</Link>
        </p>
      </div>
    </div>
  );
}
