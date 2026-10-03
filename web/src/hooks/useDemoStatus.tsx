import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, type DemoStatus } from "@/api/client";

interface DemoStatusValue {
  status: DemoStatus | null;
  unavailable: boolean;
  refresh: () => void;
}

const DemoStatusContext = createContext<DemoStatusValue>({
  status: null,
  unavailable: false,
  refresh: () => undefined,
});

const POLL_MS = 60_000;

export function DemoStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<DemoStatus | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  const refresh = useCallback(() => {
    api
      .status()
      .then((s) => {
        setStatus(s);
        setUnavailable(false);
      })
      .catch(() => setUnavailable(true));
  }, []);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  return (
    <DemoStatusContext.Provider value={{ status, unavailable, refresh }}>
      {children}
    </DemoStatusContext.Provider>
  );
}

export function useDemoStatus(): DemoStatusValue {
  return useContext(DemoStatusContext);
}
