import * as React from "react";
import { useState, useEffect } from "react";
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
  Avatar,
} from "@mui/material";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getToken } from "../../../auth";
import { apiRequest } from "../../../utils/api";
import InfoLabel from "../../../components/dashboard/InfoLabel";

// ─── Types ───────────────────────────────────────────────────────────────────

type UserResponse = {
  id: string;
  email: string;
  full_name: string | null;
  created_at?: string;
};

type UserUpdate = {
  full_name?: string;
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function initials(name: string | null | undefined): string {
  if (!name) return "?";
  return name
    .trim()
    .split(/\s+/)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .slice(0, 2)
    .join("");
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card variant="outlined" sx={{ borderRadius: 2 }}>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={600} mb={2.5}>
          {title}
        </Typography>
        {children}
      </CardContent>
    </Card>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ProfilePage() {
  const token = getToken();
  const queryClient = useQueryClient();

  // ── Fetch current user ────────────────────────────────────────────────────
  const { data: user, isLoading: userLoading, error: userError } = useQuery<UserResponse>({
    queryKey: ["me"],
    enabled: Boolean(token),
    queryFn: () => apiRequest<UserResponse>("/auth/me", {}, token),
  });

  // ── Form state – basic info ───────────────────────────────────────────────
  const [fullName, setFullName] = useState("");

  useEffect(() => {
    if (user) {
      setFullName(user.full_name ?? "");
    }
  }, [user]);

  // ── Mutations ─────────────────────────────────────────────────────────────
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const userMutation = useMutation({
    mutationFn: (payload: UserUpdate) =>
      apiRequest("/auth/me", { method: "PATCH", body: JSON.stringify(payload) }, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["me"] });
      setSaveSuccess(true);
      setSaveError(null);
    },
    onError: (error: any) => {
      setSaveError(error?.message || "Failed to save profile. Please try again.");
      setSaveSuccess(false);
    },
  });

  const handleSaveBasic = async () => {
    setSaveSuccess(false);
    setSaveError(null);

    const payload: UserUpdate = {};
    if (fullName.trim()) payload.full_name = fullName.trim();

    userMutation.mutate(payload);
  };

  if (userLoading) {
    return (
      <Box sx={{ maxWidth: 680, mx: "auto", py: 2 }}>
        <Stack spacing={3}>
          <Skeleton variant="rounded" height={56} width="100%" />
          <Skeleton variant="rounded" height={200} width="100%" />
          <Skeleton variant="rounded" height={200} width="100%" />
        </Stack>
      </Box>
    );
  }

  if (userError || !user) {
    return (
      <Box sx={{ maxWidth: 680, mx: "auto", py: 2 }}>
        <Alert severity="error">Failed to load profile. Please refresh the page.</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ maxWidth: 680, mx: "auto", py: 2, px: { xs: 0, sm: 1 } }}>
      <Stack spacing={3}>
        {/* Header */}
        <Stack direction="row" spacing={2.5} alignItems="center">
          <Avatar
            sx={{
              width: 64,
              height: 64,
              bgcolor: "primary.main",
              fontSize: 24,
              fontWeight: 700,
            }}
          >
            {initials(user?.full_name)}
          </Avatar>
          <Box>
            <Typography variant="h5" fontWeight={700}>
              {user?.full_name || "Your profile"}
            </Typography>
            <Stack direction="row" spacing={1} mt={0.5} alignItems="center">
              <Typography variant="body2" color="text.secondary">
                {user?.email}
              </Typography>
            </Stack>
          </Box>
        </Stack>

        <Divider />

        {/* Feedback */}
        {saveSuccess && (
          <Alert severity="success" onClose={() => setSaveSuccess(false)}>
            Profile updated successfully.
          </Alert>
        )}
        {saveError && (
          <Alert severity="error" onClose={() => setSaveError(null)}>
            {saveError}
          </Alert>
        )}

        {/* Basic info */}
        <Section title="Personal information">
          <Stack spacing={2.5}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField variant="filled"
                fullWidth
                label="Full name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                slotProps={{ htmlInput: { maxLength: 200 } }}
              />

            </Stack>
            <TextField variant="filled"
              fullWidth
              label={
                <InfoLabel
                  label="Email"
                  info="Email cannot be changed here. Contact support if you need to update it."
                />
              }
              InputLabelProps={{ shrink: true, sx: { pointerEvents: "auto" } }}
              value={user?.email ?? ""}
              disabled
            />
            <Box>
              <Button
                variant="contained"
                onClick={handleSaveBasic}
                disabled={userMutation.isPending}
              >
                {userMutation.isPending ? "Saving…" : "Save changes"}
              </Button>
            </Box>
          </Stack>
        </Section>
      </Stack>
    </Box>
  );
}
