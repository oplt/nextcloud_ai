import React from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { alpha } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import AppNavbar from "../../components/dashboard/AppNavbar";
import SideMenu from "../../components/dashboard/SideMenu";
import AppTheme from "../../components/shared-theme/AppTheme";
import { getToken, clearToken } from "../../auth";
import {
  chartsCustomizations,
  dataGridCustomizations,
  datePickersCustomizations,
  treeViewCustomizations,
} from "../../components/theme/customizations";
import { AlertCenterProvider } from "../../contexts/AlertCenterContext";

type User = {
  id: number;
  email: string;
  first_name?: string | null;
  last_name?: string | null;
};

const xThemeComponents = {
  ...chartsCustomizations,
  ...dataGridCustomizations,
  ...datePickersCustomizations,
};



export default function Dashboard(props: { disableCustomTheme?: boolean }) {
  const [user, setUser] = React.useState<User | null>(null);
  const [authChecked, setAuthChecked] = React.useState(false);
  const navigate = useNavigate();
  const API_BASE_RAW = import.meta.env.VITE_API_BASE_URL ?? "";
  const API_BASE_CLEAN = (API_BASE_RAW || "http://localhost:8000").replace(/\/$/, "");


  React.useEffect(() => {
    const token = getToken();
    if (!token) {
      navigate("/signin", { replace: true });
      return;
    }

    let cancelled = false;

    fetch(`${API_BASE_CLEAN}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (r) => {
        if (!r.ok) {
          if (r.status === 401 || r.status === 403) {
            throw new Error("unauthorized");
          }
          const text = await r.text().catch(() => "");
          throw new Error(text || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then((nextUser) => {
        if (cancelled) return;
        setUser(nextUser);
        setAuthChecked(true);
      })
      .catch((error) => {
        if (cancelled) return;
        if (error instanceof Error && error.message === "unauthorized") {
          clearToken();
          navigate("/signin", { replace: true });
          return;
        }
        console.warn("Failed to load user profile:", error);
        setAuthChecked(true);
      });

    return () => {
      cancelled = true;
    };
  }, [API_BASE_CLEAN, navigate]);

  if (!authChecked) return <>Loading...</>;

  return (
    <AppTheme {...props} themeComponents={xThemeComponents}>
      <CssBaseline enableColorScheme />
      <Box sx={{ display: "flex" }}>
        <SideMenu />
        <AppNavbar />
        <Box
          component="main"
          sx={(theme) => ({
            flexGrow: 1,
            backgroundColor: theme.vars
              ? `rgba(${theme.vars.palette.background.defaultChannel} / 1)`
              : alpha(theme.palette.background.default, 1),
            overflow: "auto",
          })}
        >
          <AlertCenterProvider>
            <Stack
              spacing={2}
              sx={{
                alignItems: "center",
                mx: 3,
                pb: 5,
                mt: { xs: 8, md: 0 },
              }}
            >
              {/* This is where pages will render */}
              <Outlet />
            </Stack>
          </AlertCenterProvider>
        </Box>
      </Box>
    </AppTheme>
  );
}
