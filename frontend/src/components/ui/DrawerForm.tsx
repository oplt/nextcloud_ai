import type { ReactNode } from 'react';
import CloseOutlinedIcon from '@mui/icons-material/CloseOutlined';
import IconButton from '@mui/material/IconButton';
import Drawer from '@mui/material/Drawer';

type DrawerFormProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  width?: string;
  anchor?: 'left' | 'right';
};

export function DrawerForm({
  open,
  onClose,
  title,
  description,
  actions,
  children,
  width = 'min(34rem, 100vw)',
  anchor = 'right',
}: DrawerFormProps) {
  return (
    <Drawer
      anchor={anchor}
      open={open}
      onClose={onClose}
      sx={{
        '& .MuiDrawer-paper': {
          width,
          maxWidth: '100vw',
        },
      }}
    >
      <section className="drawer-form">
        <header className="drawer-form__header">
          <div>
            <h3>{title}</h3>
            {description ? <p>{description}</p> : null}
          </div>
          <IconButton type="button" aria-label="Close panel" onClick={onClose}>
            <CloseOutlinedIcon fontSize="small" />
          </IconButton>
        </header>
        <div className="drawer-form__content">{children}</div>
        {actions ? <footer className="drawer-form__footer">{actions}</footer> : null}
      </section>
    </Drawer>
  );
}
