import * as React from 'react';
import { styled } from '@mui/material/styles';
import AppBar from '@mui/material/AppBar';
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import MuiToolbar from '@mui/material/Toolbar';
import { tabsClasses } from '@mui/material/Tabs';
import Typography from '@mui/material/Typography';
import MenuRoundedIcon from '@mui/icons-material/MenuRounded';
import DashboardRoundedIcon from '@mui/icons-material/DashboardRounded';
import SideMenuMobile from './SideMenuMobile';
import MenuButton from './MenuButton';
import ColorModeIconDropdown from '../shared-theme/ColorModeIconDropdown';

const Toolbar = styled(MuiToolbar)({
  width: '100%',
  padding: '12px',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'start',
  justifyContent: 'center',
  gap: '12px',
  flexShrink: 0,
  [`& ${tabsClasses.flexContainer}`]: {
    gap: '8px',
    p: '8px',
    pb: 0,
  },
});

export default function AppNavbar() {
  const [open, setOpen] = React.useState(false);

  const toggleDrawer = (newOpen) => () => {
    setOpen(newOpen);
  };

  return (
    <AppBar
      position="fixed"
      sx={{
        display: { xs: 'auto', md: 'none' },
        boxShadow: 0,
        bgcolor: 'background.paper',
        backgroundImage: 'none',
        borderBottom: '1px solid',
        borderColor: 'divider',
        top: 'var(--template-frame-height, 0px)',
      }}
    >
      <Toolbar variant="regular">
        <Stack
          direction="row"
          sx={{
            alignItems: 'center',
            flexGrow: 1,
            width: '100%',
            gap: 1,
          }}
        >
          <Stack
            direction="row"
            spacing={1}
            sx={{ justifyContent: 'center', mr: 'auto' }}
          >
            <CustomIcon />
            <Typography variant="h4" component="h1" sx={{ color: 'text.primary' }}>
              Farm Ops Console
            </Typography>
          </Stack>
          <ColorModeIconDropdown />
          <MenuButton aria-label="menu" onClick={toggleDrawer(true)}>
            <MenuRoundedIcon />
          </MenuButton>
          <SideMenuMobile open={open} toggleDrawer={toggleDrawer} />
        </Stack>
      </Toolbar>
    </AppBar>
  );
}

export function CustomIcon() {
  return (
    <Box
      sx={{
        width: '1.5rem',
        height: '1.5rem',
        borderRadius: '10px',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        alignSelf: 'center',
        backgroundImage:
          'linear-gradient(135deg, hsla(174, 60%, 45%, 0.95) 0%, hsla(174, 70%, 22%, 0.95) 100%)',
        color: 'hsla(36, 100%, 92%, 0.9)',
        border: '1px solid hsla(174, 45%, 40%, 0.6)',
        boxShadow: 'inset 0 2px 6px rgba(255, 255, 255, 0.2)',
      }}
    >
      <DashboardRoundedIcon color="inherit" sx={{ fontSize: '1rem' }} />
    </Box>
  );
}
