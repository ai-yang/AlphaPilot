import React, { createContext, useCallback, useContext, useRef, useState } from "react";

type ToastTone = "success" | "error" | "info";
type Toast = { id: number; tone: ToastTone; message: string };

type ToastApi = {
  push: (tone: ToastTone, message: string) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);

  const remove = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (tone: ToastTone, message: string) => {
      const id = ++seq.current;
      setToasts((current) => [...current, { id, tone, message }]);
      window.setTimeout(() => remove(id), tone === "error" ? 6000 : 3500);
    },
    [remove]
  );

  const api: ToastApi = {
    push,
    success: (message) => push("success", message),
    error: (message) => push("error", message),
    info: (message) => push("info", message)
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.tone}`} onClick={() => remove(toast.id)}>
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("ToastProvider missing");
  return ctx;
}

/**
 * Wrap async actions so they show an error toast on failure (and optional
 * success toast), while tracking an in-flight `busy` flag for disabling buttons.
 */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = useCallback(
    async (fn: () => Promise<void>, success?: string) => {
      setBusy(true);
      try {
        await fn();
        if (success) toast.success(success);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [toast]
  );
  return { busy, run };
}
