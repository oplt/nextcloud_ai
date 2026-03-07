import type { ReactElement, ReactNode } from 'react';
import { useState } from 'react';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Stack from '@mui/material/Stack';
import Collapse from '@mui/material/Collapse';
import Tooltip from '@mui/material/Tooltip';
import HomeRoundedIcon from '@mui/icons-material/HomeRounded';
import AssignmentRoundedIcon from '@mui/icons-material/AssignmentRounded';
import InsightsRoundedIcon from '@mui/icons-material/InsightsRounded';
import PrecisionManufacturingRoundedIcon from '@mui/icons-material/PrecisionManufacturingRounded';
import SettingsRoundedIcon from '@mui/icons-material/SettingsRounded';
import ExpandLess from '@mui/icons-material/ExpandLess';
import ExpandMore from '@mui/icons-material/ExpandMore';
import FlightTakeoffIcon from '@mui/icons-material/FlightTakeoff';
import TerrainIcon from '@mui/icons-material/Terrain';
import ManageAccountsRoundedIcon from '@mui/icons-material/ManageAccountsRounded';
import PermIdentityRoundedIcon from '@mui/icons-material/PermIdentityRounded';
import PhotoCameraRoundedIcon from '@mui/icons-material/PhotoCameraRounded';
import EmojiNatureRoundedIcon from '@mui/icons-material/EmojiNatureRounded';
import LocalFloristRoundedIcon from '@mui/icons-material/LocalFloristRounded';
import VisibilityRoundedIcon from '@mui/icons-material/VisibilityRounded';
import { Link, useLocation } from 'react-router-dom';

interface MenuChildItem {
  text: string;
  icon: ReactNode;
  path: string;
}

interface MenuItem {
  text: string;
  icon: ReactNode;
  path: string;
  children?: MenuChildItem[];
}

interface MenuContentProps {
  collapsed?: boolean;
}

const mainListItems: MenuItem[] = [
  { text: 'Operations', icon: <HomeRoundedIcon />, path: '/dashboard' },

];

const secondaryListItems: MenuItem[] = [
  { text: 'Profile', icon: <PermIdentityRoundedIcon />, path: '/dashboard/profile' },
  { text: 'Account', icon: <ManageAccountsRoundedIcon />, path: '/dashboard/account' },
  { text: 'Settings', icon: <SettingsRoundedIcon />, path: '/dashboard/settings' },
];

const tasksChildren = mainListItems.find((item) => item.text === 'Tasks')?.children ?? [];

export default function MenuContent({ collapsed = false }: MenuContentProps) {
  const location = useLocation();
  const isTaskRoute = (pathname: string) =>
    tasksChildren.some(
      (child) => pathname === child.path || pathname.startsWith(`${child.path}/`),
    );

  const [openTasks, setOpenTasks] = useState(() => {
    return isTaskRoute(location.pathname);
  });

  const handleTasksClick = () => {
    setOpenTasks((prevOpenTasks) => !prevOpenTasks);
  };

  const withTooltip = (label: string, node: ReactElement) =>
    collapsed ? (
      <Tooltip title={label} placement="right">
        {node}
      </Tooltip>
    ) : (
      node
    );

  const listButtonSx = collapsed
    ? { minHeight: 44, justifyContent: 'center', px: 1.5 }
    : { minHeight: 44 };

  const listIconSx = collapsed
    ? { minWidth: 0, mr: 0, justifyContent: 'center' }
    : { minWidth: 36 };

  return (
    <Stack sx={{ flexGrow: 1, p: 1, justifyContent: 'space-between' }}>
      <List dense>
        {mainListItems.map((item) => (
          <ListItem key={item.text} disablePadding sx={{ display: 'block' }}>
            {item.children && collapsed ? (
              withTooltip(
                item.text,
                <ListItemButton
                  component={Link}
                  to={item.path}
                  selected={isTaskRoute(location.pathname)}
                  sx={listButtonSx}
                >
                  <ListItemIcon sx={listIconSx}>{item.icon}</ListItemIcon>
                </ListItemButton>,
              )
            ) : item.children ? (
              <>
                <ListItemButton onClick={handleTasksClick} selected={isTaskRoute(location.pathname)}>
                  <ListItemIcon sx={listIconSx}>{item.icon}</ListItemIcon>
                  <ListItemText primary={item.text} />
                  {openTasks ? <ExpandLess /> : <ExpandMore />}
                </ListItemButton>
                <Collapse in={openTasks} timeout="auto" unmountOnExit>
                  <List component="div" disablePadding dense>
                    {item.children.map((child) => (
                      <ListItemButton
                        key={child.text}
                        component={Link}
                        to={child.path}
                        selected={
                          location.pathname === child.path ||
                          location.pathname.startsWith(`${child.path}/`)
                        }
                        sx={{ pl: 4 }}
                      >
                        <ListItemIcon sx={{ minWidth: 36 }}>{child.icon}</ListItemIcon>
                        <ListItemText primary={child.text} />
                      </ListItemButton>
                    ))}
                  </List>
                </Collapse>
              </>
            ) : (
              withTooltip(
                item.text,
                <ListItemButton
                  component={Link}
                  to={item.path}
                  selected={
                    location.pathname === item.path ||
                    location.pathname.startsWith(`${item.path}/`)
                  }
                  sx={listButtonSx}
                >
                  <ListItemIcon sx={listIconSx}>{item.icon}</ListItemIcon>
                  {!collapsed && <ListItemText primary={item.text} />}
                </ListItemButton>,
              )
            )}
          </ListItem>
        ))}
      </List>

      <List dense>
        {secondaryListItems.map((item) => (
          <ListItem key={item.text} disablePadding sx={{ display: 'block' }}>
            {withTooltip(
              item.text,
              <ListItemButton
                component={Link}
                to={item.path}
                selected={
                  location.pathname === item.path || location.pathname.startsWith(`${item.path}/`)
                }
                sx={listButtonSx}
              >
                <ListItemIcon sx={listIconSx}>{item.icon}</ListItemIcon>
                {!collapsed && <ListItemText primary={item.text} />}
              </ListItemButton>,
            )}
          </ListItem>
        ))}
      </List>
    </Stack>
  );
}
