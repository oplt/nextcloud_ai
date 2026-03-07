import * as React from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Checkbox from '@mui/material/Checkbox';
import CssBaseline from '@mui/material/CssBaseline';
import FormControlLabel from '@mui/material/FormControlLabel';
import FormLabel from '@mui/material/FormLabel';
import FormControl from '@mui/material/FormControl';
import Link from '@mui/material/Link';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import Stack from '@mui/material/Stack';
import MuiCard from '@mui/material/Card';
import Paper from '@mui/material/Paper';
import Chip from '@mui/material/Chip';
import { styled } from '@mui/material/styles';
import ForgotPassword from '../components/ForgotPassword';
import AppTheme from '../components/shared-theme/AppTheme';
import ColorModeSelect from '../components/shared-theme/ColorModeSelect';
import { SitemarkIcon } from '../components/CustomIcons';
import { useNavigate } from 'react-router-dom';
import { setToken } from '../auth';

const Card = styled(MuiCard)(({ theme }) => ({
  display: 'flex',
  flexDirection: 'column',
  alignSelf: 'center',
  width: '100%',
  padding: theme.spacing(4),
  gap: theme.spacing(2),
  borderRadius: 16,
  border: `1px solid ${(theme.vars || theme).palette.divider}`,
  background: 'hsla(0, 0%, 100%, 0.85)',
  backdropFilter: 'blur(10px)',
  boxShadow: (theme.vars || theme).palette.baseShadow,
  [theme.breakpoints.up('sm')]: {
    maxWidth: '460px',
  },
  ...theme.applyStyles('dark', {
    background: 'hsla(20, 25%, 12%, 0.85)',
  }),
}));

const SignInContainer = styled(Stack)(({ theme }) => ({
  minHeight: '100dvh',
  padding: theme.spacing(2),
  position: 'relative',
  alignItems: 'center',
  justifyContent: 'center',
  [theme.breakpoints.up('sm')]: {
    padding: theme.spacing(4),
  },
  '&::before': {
    content: '""',
    display: 'block',
    position: 'absolute',
    zIndex: -1,
    inset: 0,
    backgroundImage:
      'radial-gradient(circle at 12% 10%, hsla(174, 55%, 90%, 0.45), transparent 45%), radial-gradient(circle at 85% 15%, hsla(38, 80%, 85%, 0.4), transparent 40%)',
  },
}));

export default function SignIn(props: { disableCustomTheme?: boolean }) {
  const [emailError, setEmailError] = React.useState(false);
  const [emailErrorMessage, setEmailErrorMessage] = React.useState('');
  const [passwordError, setPasswordError] = React.useState(false);
  const [passwordErrorMessage, setPasswordErrorMessage] = React.useState('');
  const [open, setOpen] = React.useState(false);
  const [rememberMe, setRememberMe] = React.useState(false);

  React.useEffect(() => {
    const rememberedEmail = localStorage.getItem('remembered_email');
    if (rememberedEmail) {
      const emailInput = document.getElementById('email') as HTMLInputElement;
      if (emailInput) {
        emailInput.value = rememberedEmail;
      }
      setRememberMe(true);
    }
  }, []);

  const handleClickOpen = () => {
    setOpen(true);
  };

  const handleClose = () => {
    setOpen(false);
  };

  const navigate = useNavigate();

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!validateInputs()) return;

    const data = new FormData(event.currentTarget);
    const email = String(data.get('email'));
    const password = String(data.get('password'));

    const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setPasswordError(true);
      setPasswordErrorMessage(err.detail ?? 'Login failed');
      return;
    }

    const json = await res.json();
    setToken(json.access_token);

    if (rememberMe) {
      localStorage.setItem('remembered_email', email);
    } else {
      localStorage.removeItem('remembered_email');
    }

    navigate('/dashboard');
  };

  const validateInputs = () => {
    const email = document.getElementById('email') as HTMLInputElement;
    const password = document.getElementById('password') as HTMLInputElement;

    let isValid = true;

    if (!email.value || !/\S+@\S+\.\S+/.test(email.value)) {
      setEmailError(true);
      setEmailErrorMessage('Please enter a valid email address.');
      isValid = false;
    } else {
      setEmailError(false);
      setEmailErrorMessage('');
    }

    if (!password.value || password.value.length < 8) {
      setPasswordError(true);
      setPasswordErrorMessage('Password must be at least 8 characters long.');
      isValid = false;
    } else {
      setPasswordError(false);
      setPasswordErrorMessage('');
    }

    return isValid;
  };

  return (
    <AppTheme {...props}>
      <CssBaseline enableColorScheme />
      <SignInContainer>
        <ColorModeSelect sx={{ position: 'fixed', top: '1rem', right: '1rem' }} />
        <Box
          sx={{
            width: '100%',
            maxWidth: 1100,
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: '1.1fr 0.9fr' },
            gap: { xs: 4, md: 6 },
            alignItems: 'center',
          }}
        >
          <Stack spacing={3} sx={{ px: { xs: 0, md: 2 } }}>
            <SitemarkIcon />
            <Chip label="Field console" color="success" sx={{ width: 'fit-content' }} />
            <Typography variant="h2">Grower access</Typography>
            <Typography variant="body1" sx={{ color: 'text.secondary', maxWidth: 520 }}>
              Sign in to plan field flights, review imagery, and monitor telemetry across your
              farms. Access is restricted to authorized agronomy teams.
            </Typography>
            <Paper variant="outlined" sx={{ p: 2.5 }}>
              <Stack spacing={1}>
                <Typography variant="subtitle2">Field summary</Typography>
                <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                  All systems nominal. Flight queue synchronized. Telemetry link active.
                </Typography>
              </Stack>
            </Paper>
          </Stack>

          <Card variant="outlined">
            <Typography component="h1" variant="h4">
              Sign in
            </Typography>
            <Box
              component="form"
              onSubmit={handleSubmit}
              noValidate
              sx={{ display: 'flex', flexDirection: 'column', width: '100%', gap: 2 }}
            >
              <FormControl>
                <FormLabel htmlFor="email">Email</FormLabel>
                <TextField
                  error={emailError}
                  helperText={emailErrorMessage}
                  id="email"
                  type="email"
                  name="email"
                  placeholder="grower@farmco.com"
                  autoComplete="email"
                  autoFocus
                  required
                  fullWidth
                  variant="filled"
                  color={emailError ? 'error' : 'primary'}
                />
              </FormControl>
              <FormControl>
                <FormLabel htmlFor="password">Password</FormLabel>
                <TextField
                  error={passwordError}
                  helperText={passwordErrorMessage}
                  name="password"
                  placeholder="••••••"
                  type="password"
                  id="password"
                  autoComplete="current-password"
                  required
                  fullWidth
                  variant="filled"
                  color={passwordError ? 'error' : 'primary'}
                />
              </FormControl>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={rememberMe}
                    onChange={(e) => setRememberMe(e.target.checked)}
                    color="primary"
                  />
                }
                label="Remember this device"
              />
              <ForgotPassword open={open} handleClose={handleClose} />
              <Button type="submit" fullWidth variant="contained" onClick={validateInputs}>
                Sign in
              </Button>
              <Link
                component="button"
                type="button"
                onClick={handleClickOpen}
                variant="body2"
                sx={{ alignSelf: 'center' }}
              >
                Forgot your password?
              </Link>
            </Box>
            <Typography sx={{ textAlign: 'center', mt: 1 }}>
              Don&apos;t have an account?{' '}
              <Link href="/signup" variant="body2">
                Request onboarding
              </Link>
            </Typography>
          </Card>
        </Box>
      </SignInContainer>
    </AppTheme>
  );
}
