import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import Grid from '@mui/material/Grid';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import ShieldRoundedIcon from '@mui/icons-material/ShieldRounded';
import TrackChangesRoundedIcon from '@mui/icons-material/TrackChangesRounded';
import HubRoundedIcon from '@mui/icons-material/HubRounded';
import RadarRoundedIcon from '@mui/icons-material/RadarRounded';
import SatelliteAltRoundedIcon from '@mui/icons-material/SatelliteAltRounded';
import MemoryRoundedIcon from '@mui/icons-material/MemoryRounded';

const capabilities = [
  {
    title: 'Field flight planning',
    description:
      'Plan scouting, stand-count, and canopy passes with boundary-aware routing and automatic return paths.',
    icon: <TrackChangesRoundedIcon fontSize="small" />,
    meta: 'Fields + buffers + RTH',
  },
  {
    title: 'Crop health analytics',
    description:
      'NDVI, thermal, and RGB pipelines tuned for early stress detection and prescription-ready outputs.',
    icon: <ShieldRoundedIcon fontSize="small" />,
    meta: 'NDVI + thermal + RGB',
  },
  {
    title: 'Farm system integration',
    description:
      'Open APIs that connect to farm management systems, irrigation controllers, and field sensors.',
    icon: <HubRoundedIcon fontSize="small" />,
    meta: 'APIs + GIS + IoT',
  },
];

const safeguards = [
  {
    title: 'Weather-aware autonomy',
    description: 'Wind, humidity, and temperature thresholds that pause flights and protect crops.',
  },
  {
    title: 'Reliable field comms',
    description: 'Graceful handoffs across rural networks with offline-safe route caching.',
  },
  {
    title: 'Traceable fieldwork',
    description: 'Audit-ready records for every flight, image set, and agronomy recommendation.',
  },
];

export default function MainContent() {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Grid container spacing={4} alignItems="center">
        <Grid size={{ xs: 12, md: 6 }}>
          <Stack spacing={3} sx={{ animation: 'riseIn 0.6s ease both' }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <Chip
                label="Agronomy-ready autonomy"
                size="small"
                sx={{
                  bgcolor: 'hsla(174, 60%, 35%, 0.15)',
                  color: 'text.primary',
                  fontWeight: 600,
                }}
              />
              <Chip
                label="Field-secure"
                size="small"
                variant="outlined"
                sx={{ borderColor: 'hsla(174, 40%, 40%, 0.4)' }}
              />
            </Stack>
            <Typography variant="h1">
              Agronomy drone operations for healthier, higher-yield fields.
            </Typography>
            <Typography variant="body1" sx={{ color: 'text.secondary', maxWidth: 520 }}>
              A unified platform for scouting, telemetry, and imagery with agronomy-grade safety
              controls. Built to operate across large acreage, remote blocks, and mixed connectivity.
            </Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <Button variant="contained" size="large" href="/signup">
                Request onboarding
              </Button>
              <Button variant="outlined" size="large" href="/signin">
                Enter farm console
              </Button>
            </Stack>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={2}
              sx={{ pt: 2 }}
            >
              <Box>
                <Typography variant="h4">420k</Typography>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Acres mapped
                </Typography>
              </Box>
              <Box>
                <Typography variant="h4">18 min</Typography>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Scout turnaround
                </Typography>
              </Box>
              <Box>
                <Typography variant="h4">4.8x</Typography>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Faster scouting
                </Typography>
              </Box>
            </Stack>
          </Stack>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Paper
            variant="outlined"
            sx={{
              p: 3,
              position: 'relative',
              overflow: 'hidden',
              background:
                'linear-gradient(145deg, hsla(174, 50%, 94%, 0.9), hsla(36, 40%, 96%, 0.9))',
              borderColor: 'hsla(174, 30%, 40%, 0.25)',
              animation: 'riseIn 0.8s ease both',
            }}
          >
            <Box
              sx={{
                position: 'absolute',
                inset: 0,
                opacity: 0.4,
                backgroundImage:
                  'repeating-linear-gradient(0deg, transparent, transparent 18px, hsla(174, 20%, 40%, 0.15) 19px), repeating-linear-gradient(90deg, transparent, transparent 18px, hsla(174, 20%, 40%, 0.15) 19px)',
              }}
            />
            <Stack spacing={3} sx={{ position: 'relative' }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="overline" sx={{ letterSpacing: 2, color: 'text.secondary' }}>
                  Field ops snapshot
                </Typography>
                <Chip label="Field link" size="small" color="success" />
              </Stack>
              <Stack spacing={2}>
                {[
                  { label: 'Field uplink', value: 'ACTIVE', icon: <SatelliteAltRoundedIcon /> },
                  { label: 'Crop models', value: 'READY', icon: <RadarRoundedIcon /> },
                  { label: 'Flight controller', value: 'ARMED', icon: <MemoryRoundedIcon /> },
                ].map((item) => (
                  <Stack
                    key={item.label}
                    direction="row"
                    alignItems="center"
                    spacing={2}
                    sx={{
                      p: 2,
                      borderRadius: 2,
                      bgcolor: 'hsla(0, 0%, 100%, 0.7)',
                      backdropFilter: 'blur(6px)',
                      border: '1px solid hsla(174, 30%, 40%, 0.2)',
                    }}
                  >
                    <Box
                      sx={{
                        width: 34,
                        height: 34,
                        borderRadius: '12px',
                        display: 'grid',
                        placeItems: 'center',
                        bgcolor: 'hsla(174, 50%, 30%, 0.12)',
                      }}
                    >
                      {item.icon}
                    </Box>
                    <Box>
                      <Typography variant="subtitle2">{item.label}</Typography>
                      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                        {item.value}
                      </Typography>
                    </Box>
                  </Stack>
                ))}
              </Stack>
            </Stack>
          </Paper>
        </Grid>
      </Grid>

      <Box id="platform" sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        <Stack spacing={1}>
          <Typography variant="overline" sx={{ letterSpacing: 2, color: 'text.secondary' }}>
            Platform
          </Typography>
          <Typography variant="h2">Integrated scouting, telemetry, and imagery</Typography>
          <Typography variant="body1" sx={{ color: 'text.secondary', maxWidth: 720 }}>
            Coordinate field flights across fleets with reliable telemetry and agronomy-grade
            imagery workflows. Every flight, image set, and report is traceable and export-ready.
          </Typography>
        </Stack>
        <Grid container spacing={3}>
          {capabilities.map((capability, index) => (
            <Grid key={capability.title} size={{ xs: 12, md: 4 }}>
              <Paper
                variant="outlined"
                sx={{
                  p: 3,
                  height: '100%',
                  animation: 'riseIn 0.6s ease both',
                  animationDelay: `${index * 0.12}s`,
                }}
              >
                <Stack spacing={2}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Box
                      sx={{
                        width: 36,
                        height: 36,
                        borderRadius: '12px',
                        display: 'grid',
                        placeItems: 'center',
                        bgcolor: 'hsla(174, 50%, 30%, 0.12)',
                      }}
                    >
                      {capability.icon}
                    </Box>
                    <Typography variant="subtitle2" sx={{ color: 'text.secondary' }}>
                      {capability.meta}
                    </Typography>
                  </Stack>
                  <Typography variant="h6">{capability.title}</Typography>
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    {capability.description}
                  </Typography>
                </Stack>
              </Paper>
            </Grid>
          ))}
        </Grid>
      </Box>

      <Box id="safety" sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        <Stack spacing={1}>
          <Typography variant="overline" sx={{ letterSpacing: 2, color: 'text.secondary' }}>
            Safety architecture
          </Typography>
          <Typography variant="h2">Controls that keep growers in command</Typography>
        </Stack>
        <Divider />
        <Grid container spacing={3}>
          {safeguards.map((item, index) => (
            <Grid key={item.title} size={{ xs: 12, md: 4 }}>
              <Box
                sx={{
                  p: 2,
                  borderLeft: '2px solid hsla(174, 45%, 35%, 0.6)',
                  animation: 'riseIn 0.6s ease both',
                  animationDelay: `${index * 0.1}s`,
                }}
              >
                <Typography variant="h6">{item.title}</Typography>
                <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                  {item.description}
                </Typography>
              </Box>
            </Grid>
          ))}
        </Grid>
      </Box>

      <Box id="integration" sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <Typography variant="overline" sx={{ letterSpacing: 2, color: 'text.secondary' }}>
          Integration
        </Typography>
        <Typography variant="h2">Drop into existing farm stacks</Typography>
        <Typography variant="body1" sx={{ color: 'text.secondary', maxWidth: 720 }}>
          Compatible with GIS layers, weather feeds, and on-prem agronomy tools. Deployable as a
          single site or a distributed command mesh across farms and regions.
        </Typography>
      </Box>
    </Box>
  );
}
