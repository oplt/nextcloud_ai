import PublicRoundedIcon from '@mui/icons-material/PublicRounded';
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

export function SitemarkIcon() {
  return (
    <Stack direction="row" alignItems="center" spacing={1.25} sx={{ mb: 1 }}>
      <Box
        sx={{
          width: 30,
          height: 30,
          borderRadius: '10px',
          position: 'relative',
          background:
            'linear-gradient(135deg, hsla(198, 60%, 48%, 0.95), hsla(198, 70%, 24%, 0.95))',
          boxShadow: 'inset 0 1px 0 hsla(0, 0%, 100%, 0.25), 0 8px 20px hsla(198, 50%, 25%, 0.25)',
        }}
      >
        <Box
          sx={{
            position: 'absolute',
            inset: 6,
            borderRadius: '50%',
            border: '1px solid hsla(198, 60%, 90%, 0.6)',
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
            backgroundColor: 'hsla(28, 100%, 92%, 0.9)',
          }}
        />
      </Box>
      <Box>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, letterSpacing: 1 }}>
          BRIGHTPATH
        </Typography>
        <Typography variant="caption" sx={{ letterSpacing: 2, color: 'text.secondary' }}>
          CARE CONSOLE
        </Typography>
      </Box>
    </Stack>
  );
}

export function GlobeFlag() {
  return (
    <Box
      sx={{
        width: 28,
        height: 28,
        borderRadius: '50%',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        border: '1px solid',
        borderColor: 'divider',
        color: 'text.secondary',
        backgroundColor: 'background.paper',
      }}
    >
      <PublicRoundedIcon fontSize="small" />
    </Box>
  );
}
