import * as React from "react";
import { useState } from "react";
import {
  Box,
  Card,
  CardContent,
  Typography,
  TextField,
  Button,
  Stack,
  Divider,
  Alert,
  Skeleton,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  InputAdornment,
  IconButton,
} from "@mui/material";
import VisibilityRoundedIcon from "@mui/icons-material/VisibilityRounded";
import VisibilityOffRoundedIcon from "@mui/icons-material/VisibilityOffRounded";
import LockRoundedIcon from "@mui/icons-material/LockRounded";
import ShieldRoundedIcon from "@mui/icons-material/ShieldRounded";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getToken } from "../../../auth";
import { apiRequest } from "../../../utils/api";
import InfoLabel from "../../../components/dashboard/InfoLabel";

// ─── Types ────────────────────────────────────────────────────────────────────

type UserResponse = {
  id: string;
  email: string;
  full_name: string | null;
  created_at: string;
};

type UserPasswordUpdate = {
  current_password: string;
  new_password: string;
  new_password_confirm: string;
};

type TwoFASetup = {
  secret: string;
  qr_code: string; // base64 PNG
};

type TwoFAVerify = {
  token: string;
  secret?: string;
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function PasswordField({
  label,
  value,
  onChange,
  disabled,
  helperText,
  error,
  inputLabelProps,
}: {
  label: React.ReactNode;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  helperText?: string;
  error?: boolean;
  inputLabelProps?: React.ComponentProps<typeof TextField>["InputLabelProps"];
}) {
  const [show, setShow] = useState(false);
  return (
    <TextField variant="filled"
      fullWidth
      label={label}
      type={show ? "text" : "password"}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      helperText={helperText}
      error={error}
      InputLabelProps={inputLabelProps}
      slotProps={{
        input: {
          endAdornment: (
            <InputAdornment position="end">
              <IconButton
                onClick={() => setShow((s) => !s)}
                edge="end"
                tabIndex={-1}
                aria-label={show ? "Hide password" : "Show password"}
              >
                {show ? <VisibilityOffRoundedIcon /> : <VisibilityRoundedIcon />}
              </IconButton>
            </InputAdornment>
          ),
        },
      }}
    />
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card variant="outlined" sx={{ borderRadius: 2 }}>
      <CardContent>
        <Stack direction="row" spacing={1.5} alignItems="center" mb={2.5}>
          {icon && (
            <Box
              sx={{
                width: 36,
                height: 36,
                borderRadius: "50%",
                bgcolor: "primary.50",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {icon}
            </Box>
          )}
          <Typography variant="subtitle1" fontWeight={600}>
            {title}
          </Typography>
        </Stack>
        {children}
      </CardContent>
    </Card>
  );
}

// ─── Password change section ──────────────────────────────────────────────────

function PasswordSection({ token }: { token: string | null }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const mutation = useMutation({
    mutationFn: (payload: UserPasswordUpdate) =>
      apiRequest("/auth/password", { method: "PUT", body: JSON.stringify(payload) }, token),
    onSuccess: () => {
      setSuccess(true);
      setError(null);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    },
    onError: (err: any) => {
      setSuccess(false);
      setError(
        err?.message ?? "Failed to change password. Check your current password and try again."
      );
    },
  });

  const validate = (): string | null => {
    if (!currentPassword) return "Please enter your current password.";
    if (newPassword.length < 8) return "New password must be at least 8 characters.";
    if (newPassword !== confirmPassword) return "New passwords do not match.";
    if (newPassword === currentPassword) return "New password must differ from current password.";
    return null;
  };

  const handleSubmit = () => {
    setSuccess(false);
    const err = validate();
    if (err) { setError(err); return; }
    setError(null);
    mutation.mutate({ current_password: currentPassword, new_password: newPassword, new_password_confirm: confirmPassword });
  };

  return (
    <Section title="Password" icon={<LockRoundedIcon color="primary" fontSize="small" />}>
      <Stack spacing={2.5}>
        {success && (
          <Alert severity="success" onClose={() => setSuccess(false)}>
            Password changed successfully.
          </Alert>
        )}
        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}
        <PasswordField
          label="Current password"
          value={currentPassword}
          onChange={setCurrentPassword}
          disabled={mutation.isPending}
        />
        <PasswordField
          label={<InfoLabel label="New password" info="Minimum 8 characters." />}
          inputLabelProps={{ shrink: true, sx: { pointerEvents: "auto" } }}
          value={newPassword}
          onChange={setNewPassword}
          disabled={mutation.isPending}
          error={Boolean(newPassword && newPassword.length < 8)}
        />
        <PasswordField
          label="Confirm new password"
          value={confirmPassword}
          onChange={setConfirmPassword}
          disabled={mutation.isPending}
          error={Boolean(confirmPassword && newPassword !== confirmPassword)}
          helperText={
            confirmPassword && newPassword !== confirmPassword
              ? "Passwords do not match."
              : undefined
          }
        />
        <Box>
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "Updating…" : "Change password"}
          </Button>
        </Box>
      </Stack>
    </Section>
  );
}

// ─── 2FA section ──────────────────────────────────────────────────────────────

function TwoFASection({
  user,
  token,
  onRefreshUser,
}: {
  user: UserResponse;
  token: string | null;
  onRefreshUser: () => void;
}) {
  const [setupData, setSetupData] = useState<TwoFASetup | null>(null);
  const [verifyToken, setVerifyToken] = useState("");
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [verifySuccess, setVerifySuccess] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);
  const [disablePassword, setDisablePassword] = useState("");
  const [disableError, setDisableError] = useState<string | null>(null);

  // Initiate 2FA setup
  const setupMutation = useMutation({
    mutationFn: () => apiRequest<TwoFASetup>("/auth/2fa/setup", { method: "POST" }, token),
    onSuccess: (data) => {
      setSetupData(data);
      setVerifyToken("");
      setVerifyError(null);
    },
  });

  // Verify & activate 2FA
  const verifyMutation = useMutation({
    mutationFn: (payload: TwoFAVerify) =>
      apiRequest("/auth/2fa/verify", { method: "POST", body: JSON.stringify(payload) }, token),
    onSuccess: () => {
      setVerifySuccess(true);
      setVerifyError(null);
      setSetupData(null);
      onRefreshUser();
    },
    onError: () => setVerifyError("Invalid code. Please try again."),
  });

  // Disable 2FA
  const disableMutation = useMutation({
    mutationFn: (payload: { password: string }) =>
      apiRequest("/auth/2fa/disable", { method: "POST", body: JSON.stringify(payload) }, token),
    onSuccess: () => {
      setDisableOpen(false);
      setDisablePassword("");
      setDisableError(null);
      onRefreshUser();
    },
    onError: () => setDisableError("Incorrect password. Please try again."),
  });

  const handleVerify = () => {
    if (verifyToken.length !== 6) { setVerifyError("Enter the 6-digit code."); return; }
    verifyMutation.mutate({ token: verifyToken, secret: setupData?.secret });
  };

  return (
    <Section title="Two-factor authentication" icon={<ShieldRoundedIcon color="primary" fontSize="small" />}>
      <Stack spacing={2.5}>
        <Stack direction="row" spacing={2} alignItems="center">
          <Typography variant="body2" color="text.secondary" flex={1}>
            Add an extra layer of security by requiring a one-time code from an authenticator app
            when you sign in.
          </Typography>
          <Chip
            size="small"
            label={user.twofa_enabled ? "Enabled" : "Disabled"}
            color={user.twofa_enabled ? "success" : "default"}
          />
        </Stack>

        {verifySuccess && (
          <Alert severity="success" onClose={() => setVerifySuccess(false)}>
            Two-factor authentication enabled.
          </Alert>
        )}

        {!user.twofa_enabled && !setupData && (
          <Box>
            <Button
              variant="outlined"
              onClick={() => setupMutation.mutate()}
              disabled={setupMutation.isPending}
            >
              {setupMutation.isPending ? "Setting up…" : "Set up 2FA"}
            </Button>
          </Box>
        )}

        {/* Setup flow */}
        {!user.twofa_enabled && setupData && (
          <Stack spacing={2}>
            <Typography variant="body2">
              Scan this QR code with your authenticator app (Google Authenticator, Authy, etc.), then enter
              the 6-digit code below to confirm.
            </Typography>
            <Box>
              <img
                src={`data:image/png;base64,${setupData.qr_code}`}
                alt="2FA QR code"
                style={{ width: 180, height: 180, border: "1px solid #e0e0e0", borderRadius: 8 }}
              />
            </Box>
            <Typography variant="caption" color="text.secondary" fontFamily="monospace">
              Manual key: {setupData.secret}
            </Typography>
            <TextField variant="filled"
              label="Verification code"
              value={verifyToken}
              onChange={(e) => setVerifyToken(e.target.value.replace(/\D/g, "").slice(0, 6))}
              slotProps={{ htmlInput: { inputMode: "numeric", maxLength: 6 } }}
              placeholder="000000"
              sx={{ maxWidth: 200 }}
              error={Boolean(verifyError)}
              helperText={verifyError ?? undefined}
            />
            <Stack direction="row" spacing={1.5}>
              <Button
                variant="contained"
                onClick={handleVerify}
                disabled={verifyMutation.isPending || verifyToken.length !== 6}
              >
                {verifyMutation.isPending ? "Verifying…" : "Verify & enable"}
              </Button>
              <Button variant="text" onClick={() => setSetupData(null)}>
                Cancel
              </Button>
            </Stack>
          </Stack>
        )}

        {/* Disable 2FA */}
        {user.twofa_enabled && (
          <Box>
            <Button variant="outlined" color="error" onClick={() => setDisableOpen(true)}>
              Disable 2FA
            </Button>
          </Box>
        )}
      </Stack>

      {/* Disable confirm dialog */}
      <Dialog open={disableOpen} onClose={() => setDisableOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Disable two-factor authentication</DialogTitle>
        <DialogContent>
          <DialogContentText mb={2}>
            Enter your password to confirm you want to disable 2FA.
          </DialogContentText>
          {disableError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {disableError}
            </Alert>
          )}
          <PasswordField
            label="Password"
            value={disablePassword}
            onChange={setDisablePassword}
            disabled={disableMutation.isPending}
          />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={() => { setDisableOpen(false); setDisablePassword(""); setDisableError(null); }}>
            Cancel
          </Button>
          <Button
            color="error"
            variant="contained"
            disabled={disableMutation.isPending || !disablePassword}
            onClick={() => disableMutation.mutate({ password: disablePassword })}
          >
            {disableMutation.isPending ? "Disabling…" : "Disable"}
          </Button>
        </DialogActions>
      </Dialog>
    </Section>
  );
}

// ─── Account info (read-only) ─────────────────────────────────────────────────

function AccountInfoSection({ user }: { user: UserResponse }) {
  return (
    <Card variant="outlined" sx={{ borderRadius: 2 }}>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={600} mb={2.5}>
          Account information
        </Typography>
        <Stack spacing={1.5}>
          <Stack direction="row" justifyContent="space-between">
            <Typography variant="body2" color="text.secondary">Email</Typography>
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography variant="body2">{user.email}</Typography>
              {user.email_verified && (
                <Chip size="small" label="Verified" color="success" variant="outlined" />
              )}
            </Stack>
          </Stack>
          <Divider />
          <Stack direction="row" justifyContent="space-between">
            <Typography variant="body2" color="text.secondary">Member since</Typography>
            <Typography variant="body2">
              {new Date(user.created_at).toLocaleDateString()}
            </Typography>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function AccountPage() {
  const token = getToken();
  const queryClient = useQueryClient();

  const { data: user, isLoading, error } = useQuery<UserResponse>({
    queryKey: ["me"],
    enabled: Boolean(token),
    queryFn: () => apiRequest<UserResponse>("/auth/me", {}, token),
  });

  const refreshUser = () => queryClient.invalidateQueries({ queryKey: ["me"] });

  if (isLoading) {
    return (
      <Box sx={{ maxWidth: 680, mx: "auto", py: 2 }}>
        <Stack spacing={3}>
          <Skeleton variant="rounded" height={48} width="100%" />
          <Skeleton variant="rounded" height={220} width="100%" />
          <Skeleton variant="rounded" height={280} width="100%" />
        </Stack>
      </Box>
    );
  }

  if (error || !user) {
    return (
      <Box sx={{ maxWidth: 680, mx: "auto", py: 2 }}>
        <Alert severity="error">Failed to load account information. Please refresh the page.</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ maxWidth: 680, mx: "auto", py: 2, px: { xs: 0, sm: 1 } }}>
      <Stack spacing={3}>
        {/* Header */}
        <Box>
          <Typography variant="h5" fontWeight={700}>
            My account
          </Typography>
          <Typography variant="body2" color="text.secondary" mt={0.5}>
            Manage your security settings and account details.
          </Typography>
        </Box>

        <Divider />

        {/* Account overview */}
        <AccountInfoSection user={user} />

        {/* Password */}
        <PasswordSection token={token} />

        {/* 2FA */}
        <TwoFASection user={user} token={token} onRefreshUser={refreshUser} />
      </Stack>
    </Box>
  );
}
