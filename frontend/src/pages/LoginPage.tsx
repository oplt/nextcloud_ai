import { useState } from 'react';
import type { FormEvent } from 'react';
import VisibilityOffOutlinedIcon from '@mui/icons-material/VisibilityOffOutlined';
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined';
import Alert from '@mui/material/Alert';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { AppButton } from '../components/ui/AppButton';
import { AppTextField } from '../components/ui/AppTextField';

type LoginPageProps = {
  onLogin: (email: string, password: string) => Promise<void>;
  error: string | null;
  onDismissError?: () => void;
};

export function LoginPage({ onLogin, error, onDismissError }: LoginPageProps) {
  const [email, setEmail]         = useState('');
  const [password, setPassword]   = useState('');
  const [showPassword, setShowPassword] = useState(false);
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
        <Typography component="p">
          Sign in with a local admin account or arrive here via the Nextcloud
          bridge flow.
        </Typography>

        <div className="login-help" role="note">
          Docker startup seeds the admin user automatically. For local-only runs,
          use <code>python -m scripts.seed_admin</code>, then sign in with{' '}
          <code>FIRST_SUPERUSER_EMAIL</code> and{' '}
          <code>FIRST_SUPERUSER_PASSWORD</code> from{' '}
          <code>backend/.env</code>.
        </div>

        <form onSubmit={handleSubmit} className="login-form" noValidate>
          <Stack gap={1.5}>
            <AppTextField
              id="login-email"
              type="email"
              label="Email address"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                onDismissError?.();
              }}
              placeholder="admin@example.com"
              autoComplete="username"
              inputMode="email"
              autoFocus
              disabled={submitting}
            />

            <AppTextField
              id="login-password"
              type={showPassword ? 'text' : 'password'}
              label="Password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                onDismissError?.();
              }}
              placeholder="Your password"
              autoComplete="current-password"
              disabled={submitting}
              InputProps={{
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton
                      type="button"
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                      title={showPassword ? 'Hide password' : 'Show password'}
                      edge="end"
                      onClick={() => setShowPassword((visible) => !visible)}
                      disabled={submitting}
                    >
                      {showPassword ? <VisibilityOffOutlinedIcon fontSize="small" /> : <VisibilityOutlinedIcon fontSize="small" />}
                    </IconButton>
                  </InputAdornment>
                ),
              }}
            />
          </Stack>

          {error ? (
            <Alert severity="error" className="error-banner">
              {error}
            </Alert>
          ) : null}

          <AppButton type="submit" disabled={isDisabled}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </AppButton>
        </form>
      </section>
    </main>
  );
}
