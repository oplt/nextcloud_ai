import { useState } from 'react';
import type { FormEvent } from 'react';

type LoginPageProps = {
  onLogin: (email: string, password: string) => Promise<void>;
  error: string | null;
};

export function LoginPage({ onLogin, error }: LoginPageProps) {
  const [email, setEmail] = useState('admin@example.com');
  const [password, setPassword] = useState('ChangeMe123!');
  const [submitting, setSubmitting] = useState(false);

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
        <form onSubmit={handleSubmit} className="login-form">
          <label>
            <span>Email</span>
            <input value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label>
            <span>Password</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          {error ? <p className="error-banner">{error}</p> : null}
          <button type="submit" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </section>
    </main>
  );
}
