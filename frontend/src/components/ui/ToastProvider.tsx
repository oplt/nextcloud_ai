/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useId, useMemo, useState, type ReactNode } from 'react';
import Alert from '@mui/material/Alert';

export type ToastSeverity = 'success' | 'error' | 'info';

export type ToastInput = {
  message: string;
  severity?: ToastSeverity;
  durationMs?: number;
};

type ToastRecord = ToastInput & { id: string; severity: ToastSeverity };

type ToastContextValue = {
  push: (toast: ToastInput) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return ctx;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const regionId = useId();

  const push = useCallback((toast: ToastInput) => {
    const id = crypto.randomUUID();
    const severity = toast.severity ?? 'info';
    const durationMs = toast.durationMs ?? (severity === 'error' ? 9000 : 5000);
    const record: ToastRecord = { ...toast, id, severity };
    setToasts((current) => [...current, record]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, durationMs);
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div id={regionId} className="toast-region" aria-label="Notifications">
        {toasts.map((toast, index) => (
          <Alert
            key={toast.id}
            severity={toast.severity}
            variant="filled"
            className={`toast toast--${toast.severity}`}
            role={toast.severity === 'error' ? 'alert' : 'status'}
            aria-live={toast.severity === 'error' ? 'assertive' : 'polite'}
            style={{ ['--toast-index' as string]: String(index) }}
          >
            {toast.message}
          </Alert>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
