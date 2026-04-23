import { useEffect, useId, useRef, type ReactNode } from 'react';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';

import { AppButton } from './AppButton';

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'default';
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'default',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();
  const descId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCancel();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onCancel]);

  if (!open) {
    return null;
  }

  return (
    <Dialog open={open} onClose={onCancel} aria-labelledby={titleId} aria-describedby={descId} maxWidth="xs" fullWidth>
      <DialogTitle id={titleId}>{title}</DialogTitle>
      <DialogContent id={descId} dividers>
        <div className="dialog__body">{description}</div>
      </DialogContent>
      <DialogActions sx={{ p: 2 }}>
        <AppButton ref={cancelRef} type="button" variant="outlined" onClick={onCancel}>
          {cancelLabel}
        </AppButton>
        <AppButton
          type="button"
          danger={variant === 'danger'}
          color={variant === 'danger' ? 'error' : 'primary'}
          onClick={onConfirm}
        >
          {confirmLabel}
        </AppButton>
      </DialogActions>
    </Dialog>
  );
}
