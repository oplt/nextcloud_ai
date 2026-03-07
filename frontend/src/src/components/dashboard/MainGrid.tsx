import { useMemo } from 'react';
import Grid from '@mui/material/Grid';
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import Paper from '@mui/material/Paper';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import LinearProgress from '@mui/material/LinearProgress';
import Button from '@mui/material/Button';
import Alert from '@mui/material/Alert';

import Copyright from '../Copyright';
import ChartUserByCountry from './ChartUserByCountry';
import CustomizedTreeView from './CustomizedTreeView';
import CustomizedDataGrid from './CustomizedDataGrid';
import HighlightedCard from './HighlightedCard';
import PageViewsBarChart from './PageViewsBarChart';
import SessionsChart from './SessionsChart';
import StatCard, { type StatCardProps } from './StatCard';
import useAnalyticsOverview from '../../hooks/useAnalyticsOverview';
import useTelemetryWebSocket from '../../hooks/useTelemetryWebsocket';
import { useAlertCenter } from '../../contexts/AlertCenterContext';

const formatNumber = (value: number | null | undefined, suffix = '') => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value.toLocaleString()}${suffix}`;
};

const formatDuration = (minutes: number | null | undefined) => {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return '--';
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h}h ${m}m`;
};

const formatTime = (iso?: string | null) => {
  if (!iso) return '--';
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return '--';
  return dt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
};

const formatDateLabel = (iso: string) => {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

const trendFromSeries = (series: number[]) => {
  if (series.length < 2) return 'neutral' as const;
  const last = series[series.length - 1];
  const prev = series[series.length - 2];
  if (last > prev) return 'up' as const;
  if (last < prev) return 'down' as const;
  return 'neutral' as const;
};

const deltaLabelFromSeries = (series: number[]) => {
  if (series.length < 2) return undefined;
  const last = series[series.length - 1];
  const prev = series[series.length - 2];
  if (!Number.isFinite(last) || !Number.isFinite(prev) || prev === 0) return undefined;
  const pct = ((last - prev) / Math.abs(prev)) * 100;
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
};

export default function MainGrid() {
  const { data, loading, error, refresh } = useAnalyticsOverview();
  const { alerts: activeAlerts } = useAlertCenter();
  const system = data?.system;
  const wsEnabled = Boolean(system?.mavlink_connected);
  const { telemetry, isConnected } = useTelemetryWebSocket({ enabled: wsEnabled });

  const summary = data?.summary;
  const trends = data?.trends;
  const lastUpdateAge =
    system?.last_update && system.last_update > 0
      ? Math.max(0, Math.round(Date.now() / 1000 - system.last_update))
      : null;

  const days = trends?.days ?? [];
  const labels = days.map(formatDateLabel);

  const statCards = useMemo<StatCardProps[]>(() => {
    const flightCounts = trends?.flight_counts ?? [];
    const telemetryCounts = trends?.telemetry_counts ?? [];
    const flightHours = trends?.flight_hours ?? [];

    return [
      {
        title: 'Active field flights',
        value: formatNumber(summary?.active_flights),
        interval: 'Right now',
        trend: trendFromSeries(flightCounts),
        deltaLabel: deltaLabelFromSeries(flightCounts),
        data: flightCounts,
        labels,
      },
      {
        title: 'Survey hours',
        value: formatNumber(summary?.flight_hours_7d, 'h'),
        interval: 'Last 7 days',
        trend: trendFromSeries(flightHours),
        deltaLabel: deltaLabelFromSeries(flightHours),
        data: flightHours,
        labels,
      },
      {
        title: 'Telemetry frames',
        value: formatNumber(summary?.telemetry_24h),
        interval: 'Last 24 hours',
        trend: trendFromSeries(telemetryCounts),
        deltaLabel: deltaLabelFromSeries(telemetryCounts),
        data: telemetryCounts,
        labels,
      },
      {
        title: 'Avg battery health',
        value: summary?.avg_battery_24h !== null && summary?.avg_battery_24h !== undefined
          ? `${summary.avg_battery_24h}%`
          : '--',
        interval: 'Last 24 hours',
        trend:
          summary?.avg_battery_24h !== null &&
          summary?.avg_battery_24h !== undefined &&
          summary.avg_battery_24h < 40
            ? 'down'
            : 'neutral',
        data: [],
      },
    ];
  }, [labels, summary, trends]);

  const recentRows = useMemo(() => {
    if (!data?.recent_flights) return [];
    return data.recent_flights.map((flight) => {
      const normalizedStatus = String(flight.status ?? '').toLowerCase();
      return {
        id: flight.id,
        plan: flight.name,
        status:
          ['active', 'in_progress', 'running'].includes(normalizedStatus)
            ? 'Active'
            : normalizedStatus === 'paused'
              ? 'Paused'
              : ['interrupted', 'aborted'].includes(normalizedStatus)
                ? 'Interrupted'
                : normalizedStatus === 'failed'
                  ? 'Failed'
                  : 'Completed',
        duration: formatDuration(flight.duration_min),
        distance: `${flight.distance_km.toFixed(1)} km`,
        telemetry_points: flight.telemetry_points,
        started_at: formatTime(flight.started_at),
      };
    });
  }, [data?.recent_flights]);

  const telemetryBatteryRaw = telemetry?.battery?.remaining ?? telemetry?.battery_remaining ?? null;
  const telemetryBattery =
    typeof telemetryBatteryRaw === 'number' ? telemetryBatteryRaw : Number(telemetryBatteryRaw);
  const telemetryBatterySafe =
    Number.isFinite(telemetryBattery) && telemetryBattery >= 0 ? telemetryBattery : null;
  const telemetrySpeedRaw = telemetry?.status?.groundspeed ?? telemetry?.groundspeed ?? null;
  const telemetryAltRaw =
    telemetry?.position?.relative_alt ?? telemetry?.position?.relative_altitude ?? null;
  const telemetrySpeed =
    typeof telemetrySpeedRaw === 'number' ? telemetrySpeedRaw : Number(telemetrySpeedRaw);
  const telemetryAlt =
    typeof telemetryAltRaw === 'number' ? telemetryAltRaw : Number(telemetryAltRaw);
  const telemetryMode = telemetry?.mode ?? telemetry?.status?.mode ?? 'UNKNOWN';
  const gpsSatellitesRaw = telemetry?.gps?.satellites ?? telemetry?.gps?.satellite_count ?? null;
  const gpsHdopRaw = telemetry?.gps?.hdop ?? null;
  const gpsSatellites =
    typeof gpsSatellitesRaw === 'number' ? gpsSatellitesRaw : Number(gpsSatellitesRaw);
  const gpsHdop =
    typeof gpsHdopRaw === 'number' ? gpsHdopRaw : Number(gpsHdopRaw);

  const fallbackAlertItems = [
    system && !system.telemetry_running ? 'Telemetry stream is offline.' : null,
    telemetryBatterySafe !== null && telemetryBatterySafe < 30
      ? `Battery health low (${Math.round(telemetryBatterySafe)}%).`
      : null,
    system && !isConnected ? 'Live telemetry link disconnected.' : null,
  ].filter(Boolean) as string[];
  const alertItems =
    activeAlerts.length > 0
      ? activeAlerts.slice(0, 4).map((item) => `${item.title}: ${item.message}`)
      : fallbackAlertItems;

  const last7Labels = labels.slice(-7);
  const last7Flights = (trends?.flight_counts ?? []).slice(-7);
  const last7Telemetry = (trends?.telemetry_counts ?? []).slice(-7);
  const hasTrendData = (trends?.flight_hours?.length ?? 0) > 0;
  const hasWorkloadData = last7Flights.length > 0 || last7Telemetry.length > 0;
  const surveyDelta = deltaLabelFromSeries(trends?.flight_hours ?? []);
  const workloadDelta = deltaLabelFromSeries(trends?.flight_counts ?? []);

  return (
    <Box sx={{ width: '100%', maxWidth: { sm: '100%', md: '1700px' } }}>
      <Paper
        variant="outlined"
        sx={{
          p: 3,
          mb: 3,
          borderRadius: 3,
          background:
            'linear-gradient(135deg, hsla(36, 70%, 92%, 0.65), hsla(174, 55%, 92%, 0.55))',
          borderColor: 'hsla(174, 30%, 40%, 0.25)',
        }}
      >
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={3} alignItems="center">
          <Box sx={{ flex: 1 }}>
            <Typography variant="h4">Operations Pulse</Typography>
            <Typography variant="body2" sx={{ color: 'text.secondary', maxWidth: 520 }}>
              Live overview of field operations, telemetry health, and coverage readiness.
            </Typography>
          </Box>
          <Stack direction="row" spacing={2} alignItems="center">
            <Chip
              size="small"
              color={system?.telemetry_running ? 'success' : 'warning'}
              label={system?.telemetry_running ? 'Telemetry Live' : 'Telemetry Offline'}
            />
            <Chip
              size="small"
              color={system?.mavlink_connected ? 'success' : 'default'}
              label={system?.mavlink_connected ? 'MAVLink Connected' : 'MAVLink Idle'}
            />
            <Button variant="contained" size="small" onClick={refresh}>
              Refresh data
            </Button>
          </Stack>
        </Stack>
        {error && (
          <Alert severity="warning" sx={{ mt: 2 }}>
            {error}
          </Alert>
        )}
      </Paper>

      <Typography component="h2" variant="h6" sx={{ mb: 2 }}>
        Field operations overview
      </Typography>
      <Grid container spacing={2} columns={12} sx={{ mb: (theme) => theme.spacing(2) }}>
        {statCards.map((card) => (
          <Grid key={card.title} size={{ xs: 12, sm: 6, lg: 3 }}>
            <StatCard {...card} />
          </Grid>
        ))}
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <HighlightedCard />
        </Grid>
      </Grid>

      <Grid container spacing={2} columns={12} sx={{ mb: 3 }}>
        <Grid size={{ xs: 12, lg: 8 }}>
          <Paper
            variant="outlined"
            sx={{
              p: 3,
              borderRadius: 3,
              height: '100%',
              borderColor: 'hsla(174, 30%, 40%, 0.25)',
            }}
          >
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Stack>
                <Typography variant="h6">Live telemetry</Typography>
                <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                  Streaming vehicle health and GPS quality.
                </Typography>
              </Stack>
              <Chip
                size="small"
                color={isConnected ? 'success' : 'default'}
                label={isConnected ? 'Live' : 'Offline'}
              />
            </Stack>
            <Divider sx={{ my: 2 }} />
            <Grid container spacing={2}>
              <Grid size={{ xs: 6, md: 3 }}>
                <Typography variant="caption" color="text.secondary">
                  Flight mode
                </Typography>
                <Typography variant="h6">{telemetryMode}</Typography>
              </Grid>
              <Grid size={{ xs: 6, md: 3 }}>
                <Typography variant="caption" color="text.secondary">
                  Altitude
                </Typography>
                <Typography variant="h6">
                  {Number.isFinite(telemetryAlt) ? `${telemetryAlt.toFixed(1)} m` : '--'}
                </Typography>
              </Grid>
              <Grid size={{ xs: 6, md: 3 }}>
                <Typography variant="caption" color="text.secondary">
                  Groundspeed
                </Typography>
                <Typography variant="h6">
                  {Number.isFinite(telemetrySpeed) ? `${telemetrySpeed.toFixed(1)} m/s` : '--'}
                </Typography>
              </Grid>
              <Grid size={{ xs: 6, md: 3 }}>
                <Typography variant="caption" color="text.secondary">
                  Battery
                </Typography>
                <Typography variant="h6">
                  {telemetryBatterySafe !== null
                    ? `${Math.round(telemetryBatterySafe)}%`
                    : '--'}
                </Typography>
              </Grid>
            </Grid>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ mt: 3 }}>
              <Box sx={{ flex: 1 }}>
                <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
                  <Typography variant="caption" color="text.secondary">
                    GPS strength
                  </Typography>
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>
                    {Number.isFinite(gpsSatellites) ? gpsSatellites : '--'} sats • HDOP{' '}
                    {Number.isFinite(gpsHdop) ? gpsHdop.toFixed(1) : '--'}
                  </Typography>
                </Stack>
                <LinearProgress
                  variant="determinate"
                  value={
                    Number.isFinite(gpsSatellites)
                      ? Math.min(100, (gpsSatellites as number) * 8)
                      : 0
                  }
                  sx={{ height: 6, borderRadius: 999 }}
                />
              </Box>
              <Box sx={{ flex: 1 }}>
                <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
                  <Typography variant="caption" color="text.secondary">
                    Battery reserve
                  </Typography>
                  <Typography variant="caption" sx={{ fontWeight: 600 }}>
                    {telemetryBatterySafe !== null
                      ? `${Math.round(telemetryBatterySafe)}%`
                      : '--'}
                  </Typography>
                </Stack>
                <LinearProgress
                  variant="determinate"
                  value={telemetryBatterySafe ?? 0}
                  color={
                    telemetryBatterySafe !== null && telemetryBatterySafe < 30
                      ? 'error'
                      : 'primary'
                  }
                  sx={{ height: 6, borderRadius: 999 }}
                />
              </Box>
            </Stack>
          </Paper>
        </Grid>
        <Grid size={{ xs: 12, lg: 4 }}>
          <Stack spacing={2} sx={{ height: '100%' }}>
            <ChartUserByCountry segments={data?.coverage} totalLabel="Flight coverage" />
            <Paper
              variant="outlined"
              sx={{
                p: 2.5,
                borderRadius: 3,
                borderColor: 'hsla(174, 30%, 40%, 0.25)',
              }}
            >
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Operational alerts
              </Typography>
              {alertItems.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  No critical alerts detected. Systems are operating within safe bounds.
                </Typography>
              ) : (
                <Stack spacing={1}>
                  {alertItems.map((item) => (
                    <Alert key={item} severity="warning">
                      {item}
                    </Alert>
                  ))}
                </Stack>
              )}
            </Paper>
          </Stack>
        </Grid>
      </Grid>

      <Grid container spacing={2} columns={12} sx={{ mb: 3 }}>
        <Grid size={{ xs: 12, md: 6 }}>
          <SessionsChart
            title="Survey hours"
            totalValue={formatNumber(summary?.flight_hours_7d, 'h')}
            deltaLabel={surveyDelta}
            subtitle="Survey hours per day for the last 30 days"
            labels={hasTrendData ? labels : undefined}
            series={
              hasTrendData
                ? [
                    {
                      id: 'hours',
                      label: 'Hours',
                      data: trends?.flight_hours ?? [],
                    },
                  ]
                : undefined
            }
          />
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <PageViewsBarChart
            title="Workload mix"
            totalValue={formatNumber(summary?.flights_24h)}
            deltaLabel={workloadDelta}
            subtitle="Flights and telemetry points for the last 7 days"
            labels={hasWorkloadData ? last7Labels : undefined}
            series={
              hasWorkloadData
                ? [
                    { id: 'flights', label: 'Flights', data: last7Flights },
                    { id: 'telemetry', label: 'Telemetry', data: last7Telemetry },
                  ]
                : undefined
            }
          />
        </Grid>
      </Grid>

      <Typography component="h2" variant="h6" sx={{ mb: 2 }}>
        Equipment health
      </Typography>
      <Grid container spacing={2} columns={12}>
        <Grid size={{ xs: 12, lg: 9 }}>
          <CustomizedDataGrid rows={recentRows} loading={loading} />
        </Grid>
        <Grid size={{ xs: 12, lg: 3 }}>
          <Stack gap={2} direction={{ xs: 'column', sm: 'row', lg: 'column' }}>
            <CustomizedTreeView
              summary={summary}
              system={system}
              coverage={data?.coverage}
            />
            <Paper
              variant="outlined"
              sx={{
                p: 2.5,
                borderRadius: 3,
                borderColor: 'hsla(174, 30%, 40%, 0.25)',
              }}
            >
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                System status
              </Typography>
              <Stack spacing={1}>
                <Stack direction="row" justifyContent="space-between">
                  <Typography variant="body2" color="text.secondary">
                    WebSocket
                  </Typography>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {system?.telemetry_running ? 'Running' : 'Stopped'}
                  </Typography>
                </Stack>
                <Stack direction="row" justifyContent="space-between">
                  <Typography variant="body2" color="text.secondary">
                    Active clients
                  </Typography>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {system?.active_connections ?? 0}
                  </Typography>
                </Stack>
                <Stack direction="row" justifyContent="space-between">
                  <Typography variant="body2" color="text.secondary">
                    MAVLink
                  </Typography>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {system?.mavlink_connected ? 'Connected' : 'Idle'}
                  </Typography>
                </Stack>
                <Stack direction="row" justifyContent="space-between">
                  <Typography variant="body2" color="text.secondary">
                    Last telemetry
                  </Typography>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {lastUpdateAge !== null ? `${lastUpdateAge}s ago` : '--'}
                  </Typography>
                </Stack>
              </Stack>
            </Paper>
          </Stack>
        </Grid>
      </Grid>
      <Copyright sx={{ my: 4 }} />
    </Box>
  );
}
