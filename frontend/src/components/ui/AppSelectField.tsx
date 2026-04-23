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

export function AppSelectField({ label, options, id, ...props }: AppSelectFieldProps) {
  const labelId = `${id ?? label.replace(/\s+/g, '-').toLowerCase()}-label`;

  return (
    <FormControl fullWidth size="small">
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select<string> labelId={labelId} id={id} label={label} {...props}>
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value}>
            {option.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
