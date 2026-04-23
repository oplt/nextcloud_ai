import TextField from '@mui/material/TextField';
import type { TextFieldProps } from '@mui/material/TextField';

export function AppTextField(props: TextFieldProps) {
  return <TextField fullWidth size="small" variant="outlined" {...props} />;
}
