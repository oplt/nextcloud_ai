import * as React from 'react';
import MuiAvatar from '@mui/material/Avatar';
import MuiListItemAvatar from '@mui/material/ListItemAvatar';
import MenuItem from '@mui/material/MenuItem';
import ListItemText from '@mui/material/ListItemText';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListSubheader from '@mui/material/ListSubheader';
import Select, { selectClasses } from '@mui/material/Select';
import type { SelectChangeEvent } from "@mui/material/Select";
import Divider from '@mui/material/Divider';
import { styled } from '@mui/material/styles';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import DevicesRoundedIcon from '@mui/icons-material/DevicesRounded';
import SmartphoneRoundedIcon from '@mui/icons-material/SmartphoneRounded';
import ConstructionRoundedIcon from '@mui/icons-material/ConstructionRounded';

const Avatar = styled(MuiAvatar)(({ theme }) => ({
  width: 28,
  height: 28,
  backgroundColor: (theme.vars || theme).palette.background.paper,
  color: (theme.vars || theme).palette.text.secondary,
  border: `1px solid ${(theme.vars || theme).palette.divider}`,
}));

const ListItemAvatar = styled(MuiListItemAvatar)({
  minWidth: 0,
  marginRight: 12,
});

export default function SelectContent() {
  const [company, setCompany] = React.useState('');

  const handleChange = (event: SelectChangeEvent) => {
    setCompany(event.target.value as string);
  };

  return (
    <Select
      labelId="company-select"
      id="company-simple-select"
      value={company}
      onChange={handleChange}
      displayEmpty
      inputProps={{ 'aria-label': 'Select company' }}
      fullWidth
      sx={{
        maxHeight: 56,
        width: 215,
        '&.MuiList-root': {
          p: '8px',
        },
        [`& .${selectClasses.select}`]: {
          display: 'flex',
          alignItems: 'center',
          gap: '2px',
          pl: 1,
        },
      }}
    >
      <ListSubheader sx={{ pt: 0 }}>Active farms</ListSubheader>
      <MenuItem value="">
        <ListItemAvatar>
          <Avatar alt="North Orchard">
            <DevicesRoundedIcon sx={{ fontSize: '1rem' }} />
          </Avatar>
        </ListItemAvatar>
        <ListItemText primary="North Orchard" secondary="Apple blocks" />
      </MenuItem>
      <MenuItem value={10}>
        <ListItemAvatar>
          <Avatar alt="East Row Crops">
            <SmartphoneRoundedIcon sx={{ fontSize: '1rem' }} />
          </Avatar>
        </ListItemAvatar>
        <ListItemText primary="East Row Crops" secondary="Corn + soy" />
      </MenuItem>
      <MenuItem value={20}>
        <ListItemAvatar>
          <Avatar alt="South Vineyards">
            <DevicesRoundedIcon sx={{ fontSize: '1rem' }} />
          </Avatar>
        </ListItemAvatar>
        <ListItemText primary="South Vineyards" secondary="Irrigation check" />
      </MenuItem>
      <ListSubheader>Staging</ListSubheader>
      <MenuItem value={30}>
        <ListItemAvatar>
          <Avatar alt="Demo Fields">
            <ConstructionRoundedIcon sx={{ fontSize: '1rem' }} />
          </Avatar>
        </ListItemAvatar>
        <ListItemText primary="Demo Fields" secondary="Trial plots" />
      </MenuItem>
      <Divider sx={{ mx: -1 }} />
      <MenuItem value={40}>
        <ListItemIcon>
          <AddRoundedIcon />
        </ListItemIcon>
        <ListItemText primary="Register new farm" secondary="Onboarding workflow" />
      </MenuItem>
    </Select>
  );
}
