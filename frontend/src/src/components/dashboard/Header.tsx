import Stack from '@mui/material/Stack';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Drawer from '@mui/material/Drawer';
import Paper from '@mui/material/Paper';
import Alert from '@mui/material/Alert';
import Divider from '@mui/material/Divider';
import Typography from '@mui/material/Typography';
import NotificationsRoundedIcon from '@mui/icons-material/NotificationsRounded';
import CustomDatePicker from './CustomDatePicker';
import NavbarBreadcrumbs from './NavbarBreadcrumbs';
import MenuButton from './MenuButton';
import Chip from '@mui/material/Chip';
import ColorModeIconDropdown from '../shared-theme/ColorModeIconDropdown';
import CircularProgress from '@mui/material/CircularProgress';
import { useState } from 'react';

import Search from './Search';
import { useAlertCenter, type AlertItem } from '../../contexts/AlertCenterContext';

const severityColor = (severity: string): 'error' | 'warning' | 'info' | 'default' => {
  const normalized = String(severity || '').toLowerCase();
  if (normalized === 'critical' || normalized === 'high') return 'error';
  if (normalized === 'medium') return 'warning';
  if (normalized === 'low') return 'info';
  return 'default';
};

const formatTimestamp = (value: string) => {
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

function AlertCard({
  item,
  onAcknowledge,
  onResolve,
  pending,
}: {
  item: AlertItem;
  pending: boolean;
  onAcknowledge: () => Promise<void>;
  onResolve: () => Promise<void>;
}) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
      <Stack spacing={1}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
          <Typography variant="subtitle2">{item.title}</Typography>
          <Chip size="small" color={severityColor(item.severity)} label={item.severity.toUpperCase()} />
        </Stack>
        <Typography variant="body2" sx={{ color: 'text.secondary' }}>
          {item.message}
        </Typography>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          Triggered {formatTimestamp(item.last_triggered_at)}
        </Typography>
        <Stack direction="row" spacing={1}>
          <Button
            size="small"
            variant="outlined"
            disabled={pending || item.status !== 'open'}
            onClick={() => void onAcknowledge()}
          >
            Acknowledge
          </Button>
          <Button
            size="small"
            variant="contained"
            color="success"
            disabled={pending}
            onClick={() => void onResolve()}
          >
            Resolve
          </Button>
        </Stack>
      </Stack>
    </Paper>
  );
}

export default function Header() {
  const { alerts, openCount, loading, drawerOpen, setDrawerOpen, refresh, acknowledgeAlert, resolveAlert } =
    useAlertCenter();
  const [pendingAlertId, setPendingAlertId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleAcknowledge = async (alertId: number) => {
    setPendingAlertId(alertId);
    setActionError(null);
    try {
      await acknowledgeAlert(alertId);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to acknowledge alert');
    } finally {
      setPendingAlertId(null);
    }
  };

  const handleResolve = async (alertId: number) => {
    setPendingAlertId(alertId);
    setActionError(null);
    try {
      await resolveAlert(alertId);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to resolve alert');
    } finally {
      setPendingAlertId(null);
    }
  };

  return (
    <>
      <Stack
        direction="row"
        sx={{
          display: { xs: 'none', md: 'flex' },
          width: '100%',
          alignItems: { xs: 'flex-start', md: 'center' },
          justifyContent: 'space-between',
          maxWidth: { sm: '100%', md: '1700px' },
          pt: 1.5,
        }}
        spacing={2}
      >
        <NavbarBreadcrumbs />
        <Stack direction="row" sx={{ gap: 1 }}>
          <Search />
          <CustomDatePicker />
          <Chip size="small" color="success" label="Telemetry live" />
          <MenuButton
            showBadge={openCount > 0}
            aria-label="Open notifications"
            onClick={() => setDrawerOpen(true)}
          >
            <NotificationsRoundedIcon />
          </MenuButton>
          <ColorModeIconDropdown />
        </Stack>
      </Stack>
      <Drawer anchor="right" open={drawerOpen} onClose={() => setDrawerOpen(false)}>
        <Box sx={{ width: { xs: 320, sm: 420 }, p: 2 }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
            <Typography variant="h6">Operational Alerts</Typography>
            <Button size="small" onClick={() => void refresh()}>
              Refresh
            </Button>
          </Stack>
          <Typography variant="body2" sx={{ color: 'text.secondary', mb: 1 }}>
            {openCount} open alerts
          </Typography>
          <Divider sx={{ mb: 2 }} />
          {actionError && (
            <Alert severity="error" sx={{ mb: 1.5 }}>
              {actionError}
            </Alert>
          )}
          {loading && (
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
              <CircularProgress size={16} />
              <Typography variant="body2">Updating alerts...</Typography>
            </Stack>
          )}
          {alerts.length === 0 ? (
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>
              No active alerts.
            </Typography>
          ) : (
            <Stack spacing={1.25}>
              {alerts.map((item) => (
                <AlertCard
                  key={item.id}
                  item={item}
                  pending={pendingAlertId === item.id}
                  onAcknowledge={() => handleAcknowledge(item.id)}
                  onResolve={() => handleResolve(item.id)}
                />
              ))}
            </Stack>
          )}
        </Box>
      </Drawer>
    </>
  );
}
