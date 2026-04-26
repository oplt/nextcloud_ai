import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import type { SelectProps } from '@mui/material/Select';

type Option = {
  label: string;
  value: string;
};

type AppSelectFieldProps = Omit<SelectProps<string>, 'label'> & {
  label: string;
  options: Option[];
};

export function AppSelectField({ label, options, id, value, ...props }: AppSelectFieldProps) {
  const labelId = `${id ?? label.replace(/\s+/g, '-').toLowerCase()}-label`;
  const hasMatchingOption =
    value === undefined || value === '' || options.some((option) => option.value === value);
  const safeValue = hasMatchingOption ? value : '';

  return (
    <FormControl fullWidth size="small">
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select<string> {...props} labelId={labelId} id={id} label={label} value={safeValue}>
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value}>
            {option.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
