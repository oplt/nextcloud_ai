import { useState } from 'react';
import Avatar from '@mui/material/Avatar';
import MuiDrawer, { drawerClasses } from '@mui/material/Drawer';
import Box from '@mui/material/Box';
import Divider from '@mui/material/Divider';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import ChevronLeftRoundedIcon from '@mui/icons-material/ChevronLeftRounded';
import ChevronRightRoundedIcon from '@mui/icons-material/ChevronRightRounded';
import MenuContent from './MenuContent';

const expandedDrawerWidth = 240;
const collapsedDrawerWidth = 72;

export default function SideMenu() {
  const [collapsed, setCollapsed] = useState(false);
  const drawerWidth = collapsed ? collapsedDrawerWidth : expandedDrawerWidth;

  return (
    <MuiDrawer
      variant="permanent"
      sx={(theme) => ({
        display: { xs: 'none', md: 'block' },
        width: drawerWidth,
        flexShrink: 0,
        whiteSpace: 'nowrap',
        transition: theme.transitions.create('width', {
          duration: theme.transitions.duration.standard,
          easing: theme.transitions.easing.sharp,
        }),
        [`& .${drawerClasses.paper}`]: {
          backgroundColor: 'background.paper',
          width: drawerWidth,
          overflowX: 'hidden',
          boxSizing: 'border-box',
          transition: theme.transitions.create('width', {
            duration: theme.transitions.duration.standard,
            easing: theme.transitions.easing.sharp,
          }),
        },
      })}
    >
      <Box
        sx={{
          mt: 'calc(var(--template-frame-height, 0px) + 4px)',
          p: 1,
        }}
      >
        <Stack
          direction="row"
          sx={{
            px: 1,
            py: 0.75,
            gap: 1,
            alignItems: 'center',
            justifyContent: collapsed ? 'center' : 'space-between',
            borderTop: '1px solid',
            borderColor: 'divider',
          }}
        >
          {!collapsed && (
            <Stack direction="row" sx={{ gap: 1, alignItems: 'center', minWidth: 0 }}>
              <Avatar
                sizes="small"
                alt="Field Manager"
                src=""
                sx={{ width: 36, height: 36 }}
              />
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="body2" sx={{ fontWeight: 500, lineHeight: '16px' }}>
                  Field Manager
                </Typography>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Farm session
                </Typography>
              </Box>
            </Stack>
          )}
          <Tooltip title={collapsed ? 'Expand menu' : 'Collapse menu'} placement="right">
            <IconButton
              size="small"
              onClick={() => setCollapsed((prev) => !prev)}
              aria-label={collapsed ? 'Expand sidebar menu' : 'Collapse sidebar menu'}
            >
              {collapsed ? (
                <ChevronRightRoundedIcon fontSize="small" />
              ) : (
                <ChevronLeftRoundedIcon fontSize="small" />
              )}
            </IconButton>
          </Tooltip>
        </Stack>
      </Box>
      <Divider />
      <Box
        sx={{
          overflow: 'auto',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <MenuContent collapsed={collapsed} />
      </Box>
    </MuiDrawer>
  );
}
