import Checkbox from '@mui/material/Checkbox';
import type { CheckboxProps } from '@mui/material/Checkbox';

export function AppCheckbox(props: CheckboxProps) {
  return <Checkbox size="small" sx={{ p: 0.25 }} {...props} />;
}
