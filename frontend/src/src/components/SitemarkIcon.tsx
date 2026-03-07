import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

export default function SitemarkIcon() {
  return (
    <Stack direction="row" alignItems="center" spacing={1.25} sx={{ mr: 2 }}>
      <Box
        sx={{
          width: 30,
          height: 30,
          borderRadius: '10px',
          position: 'relative',
          background:
            'linear-gradient(135deg, hsla(174, 60%, 45%, 0.9), hsla(174, 70%, 22%, 0.95))',
          boxShadow: 'inset 0 1px 0 hsla(0, 0%, 100%, 0.25), 0 8px 20px hsla(174, 50%, 25%, 0.25)',
        }}
      >
        <Box
          sx={{
            position: 'absolute',
            inset: 6,
            borderRadius: '50%',
            border: '1px solid hsla(174, 60%, 90%, 0.6)',
          }}
        />
        <Box
          sx={{
            position: 'absolute',
            left: '50%',
            top: '50%',
            width: 5,
            height: 5,
            transform: 'translate(-50%, -50%)',
            borderRadius: '50%',
            backgroundColor: 'hsla(36, 100%, 92%, 0.9)',
          }}
        />
      </Box>
      <Box>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, letterSpacing: 1 }}>
          TERRAFIELD
        </Typography>
        <Typography variant="caption" sx={{ letterSpacing: 2, color: 'text.secondary' }}>
          AGRONOMY DRONES
        </Typography>
      </Box>
    </Stack>
  );
}
