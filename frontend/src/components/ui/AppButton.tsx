import { forwardRef } from 'react';
import Button from '@mui/material/Button';
import type { ButtonProps } from '@mui/material/Button';

type AppButtonProps = ButtonProps & {
  danger?: boolean;
};

export const AppButton = forwardRef<HTMLButtonElement, AppButtonProps>(function AppButton(
  { danger = false, color, variant = 'contained', ...props },
  ref,
) {
  return (
    <Button
      ref={ref}
      color={danger ? 'error' : color}
      variant={variant}
      {...props}
    />
  );
});
