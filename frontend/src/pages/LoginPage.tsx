import { useState } from 'react';
import type { FormEvent } from 'react';

type LoginPageProps = {
  onLogin: (email: string, password: string) => Promise<void>;
  error: string | null;
};

export function LoginPage({ onLogin, error }: LoginPageProps) {
  const [email, setEmail]         = useState('');
  const [password, setPassword]   = useState('');
  const [submitting, setSubmitting] = useState(false);

  const isDisabled = submitting || !email.trim() || !password;

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onLogin(email, password);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-shell">
      <section className="login-panel">
        {/* Logo mark */}
        <div className="login-panel__logo" aria-hidden="true">NC</div>

        <span className="eyebrow">Private RAG Workspace</span>
        <h1>Nextcloud AI Server</h1>
        <p>
          Sign in with a local admin account or arrive here via the Nextcloud
          bridge flow.
        </p>

        <div className="login-help" role="note">
          First login: run{' '}
          <code>python -m backend.scripts.seed_admin</code> or{' '}
          <code>docker compose exec backend python -m backend.scripts.seed_admin</code>
          , then use{' '}
          <code>FIRST_SUPERUSER_EMAIL</code> and{' '}
          <code>FIRST_SUPERUSER_PASSWORD</code> from{' '}
          <code>backend/.env</code>.
        </div>

        <form onSubmit={handleSubmit} className="login-form" noValidate>
          <label htmlFor="login-email">
            <span>Email address</span>
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="admin@example.com"
              autoComplete="username"
              inputMode="email"
              autoFocus
              disabled={submitting}
            />
          </label>

          <label htmlFor="login-password">
            <span>Password</span>
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Your password"
              autoComplete="current-password"
              disabled={submitting}
            />
          </label>

          {error ? (
            <p className="error-banner" role="alert">
              {error}
            </p>
          ) : null}

          <button type="submit" disabled={isDisabled}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </section>
    </main>
  );
}
