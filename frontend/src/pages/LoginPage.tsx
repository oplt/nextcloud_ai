import { useState } from 'react';
import type { FormEvent } from 'react';

type LoginPageProps = {
  onLogin: (email: string, password: string) => Promise<void>;
  error: string | null;
};

export function LoginPage({ onLogin, error }: LoginPageProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const isDisabled = submitting || !email.trim() || !password;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
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
        <p className="eyebrow">Private RAG Workspace</p>
        <h1>Nextcloud AI Server</h1>
        <p>Sign in with a local admin account or arrive here via the Nextcloud bridge flow.</p>
        <p className="login-help">
          First login: run <code>python -m backend.scripts.seed_admin</code> or
          <code> docker compose exec backend python -m backend.scripts.seed_admin</code>,
          then use <code>FIRST_SUPERUSER_EMAIL</code> and <code>FIRST_SUPERUSER_PASSWORD</code>
          from <code>backend/.env</code>.
        </p>
        <form onSubmit={handleSubmit} className="login-form">
          <label>
            <span>Email</span>
            <input
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="Enter your admin email"
              autoComplete="username"
            />
          </label>
          <label>
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter your password"
              autoComplete="current-password"
            />
          </label>
          {error ? <p className="error-banner">{error}</p> : null}
          <button type="submit" disabled={isDisabled}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </section>
    </main>
  );
}
