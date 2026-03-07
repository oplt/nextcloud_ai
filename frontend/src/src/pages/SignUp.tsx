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

const SignUpContainer = styled(Stack)(({ theme }) => ({
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
      'radial-gradient(circle at 20% 12%, hsla(174, 55%, 90%, 0.45), transparent 45%), radial-gradient(circle at 84% 18%, hsla(38, 80%, 85%, 0.35), transparent 40%)',
  },
}));

export default function SignUp(props: { disableCustomTheme?: boolean }) {
  const [emailError, setEmailError] = React.useState(false);
  const [emailErrorMessage, setEmailErrorMessage] = React.useState('');
  const [passwordError, setPasswordError] = React.useState(false);
  const [passwordErrorMessage, setPasswordErrorMessage] = React.useState('');
  const [nameError, setNameError] = React.useState(false);
  const [nameErrorMessage, setNameErrorMessage] = React.useState('');

  const validateInputs = () => {
    const email = document.getElementById('email') as HTMLInputElement;
    const password = document.getElementById('password') as HTMLInputElement;
    const name = document.getElementById('name') as HTMLInputElement;

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

    if (!name.value || name.value.length < 1) {
      setNameError(true);
      setNameErrorMessage('Name is required.');
      isValid = false;
    } else {
      setNameError(false);
      setNameErrorMessage('');
    }

    return isValid;
  };

  const navigate = useNavigate();

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!validateInputs()) return;

    const data = new FormData(event.currentTarget);
    const full_name = String(data.get('name') ?? '').trim();
    const email = String(data.get('email'));
    const password = String(data.get('password'));
    const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

    const res = await fetch(`${API_BASE}/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ full_name, email, password }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setEmailError(true);
      setEmailErrorMessage(err.detail ?? 'Sign up failed');
      return;
    }

    const json = await res.json();
    setToken(json.access_token);
    navigate('/dashboard');
  };

  return (
    <AppTheme {...props}>
      <CssBaseline enableColorScheme />
      <ColorModeSelect sx={{ position: 'fixed', top: '1rem', right: '1rem' }} />
      <SignUpContainer>
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
            <Chip label="Grower onboarding" color="warning" sx={{ width: 'fit-content' }} />
            <Typography variant="h2">Request grower access</Typography>
            <Typography variant="body1" sx={{ color: 'text.secondary', maxWidth: 520 }}>
              Create a grower profile. Access requests are reviewed by the agronomy operations
              team and validated against farm onboarding requirements.
            </Typography>
            <Paper variant="outlined" sx={{ p: 2.5 }}>
              <Stack spacing={1}>
                <Typography variant="subtitle2">What to expect</Typography>
                <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                  Approval typically requires farm ownership verification, device enrollment, and
                  sensor calibration details.
                </Typography>
              </Stack>
            </Paper>
          </Stack>

          <Card variant="outlined">
            <Typography component="h1" variant="h4">
              Request onboarding
            </Typography>
            <Box
              component="form"
              onSubmit={handleSubmit}
              sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}
            >
              <FormControl>
                <FormLabel htmlFor="name">Full name</FormLabel>
                <TextField variant="filled"
                  autoComplete="name"
                  name="name"
                  required
                  fullWidth
                  id="name"
                  placeholder="Alex Morgan"
                  error={nameError}
                  helperText={nameErrorMessage}
                  color={nameError ? 'error' : 'primary'}
                />
              </FormControl>
              <FormControl>
                <FormLabel htmlFor="email">Email</FormLabel>
                <TextField
                  required
                  fullWidth
                  id="email"
                  placeholder="grower@farmco.com"
                  name="email"
                  autoComplete="email"
                  variant="filled"
                  error={emailError}
                  helperText={emailErrorMessage}
                  color={emailError ? 'error' : 'primary'}
                />
              </FormControl>
              <FormControl>
                <FormLabel htmlFor="password">Password</FormLabel>
                <TextField
                  required
                  fullWidth
                  name="password"
                  placeholder="••••••"
                  type="password"
                  id="password"
                  autoComplete="new-password"
                  variant="filled"
                  error={passwordError}
                  helperText={passwordErrorMessage}
                  color={passwordError ? 'error' : 'primary'}
                />
              </FormControl>
              <FormControlLabel
                control={<Checkbox value="allowExtraEmails" color="primary" />}
                label="Notify me about platform updates"
              />
              <Button type="submit" fullWidth variant="contained" onClick={validateInputs}>
                Submit request
              </Button>
            </Box>
            <Typography sx={{ textAlign: 'center', mt: 1 }}>
              Already have an account?{' '}
              <Link href="/signin" variant="body2">
                Sign in
              </Link>
            </Typography>
          </Card>
        </Box>
      </SignUpContainer>
    </AppTheme>
  );
}
