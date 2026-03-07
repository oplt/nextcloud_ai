import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getToken } from "../auth";

export type AnalyticsOverview = {
  summary: {
    active_flights: number;
    flights_24h: number;
    telemetry_24h: number;
    flight_hours_7d: number;
    avg_battery_24h: number | null;
  };
  trends: {
    days: string[];
    flight_hours: number[];
    flight_counts: number[];
    telemetry_counts: number[];
  };
  coverage: { label: string; value: number }[];
  recent_flights: {
    id: number;
    name: string;
    status: string;
    started_at: string;
    ended_at: string | null;
    duration_min: number;
    distance_km: number;
    telemetry_points: number;
  }[];
  events: {
    id: number;
    flight_id: number;
    type: string;
    created_at: string;
    data: Record<string, any>;
  }[];
  system: {
    telemetry_running: boolean;
    active_connections: number;
    last_update: number;
    mavlink_connected: boolean;
  };
};

export default function useAnalyticsOverview(pollMs = 30000) {
  const apiBaseRaw = (import.meta.env.VITE_API_BASE_URL ?? "").trim();
  const API_BASE = (apiBaseRaw || "http://localhost:8000").replace(/\/$/, "");
  const [data, setData] = useState<AnalyticsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const fetchOnce = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setError("Not authenticated");
      setLoading(false);
      return;
    }

    try {
      setError(null);
      const res = await fetch(`${API_BASE}/analytics/overview`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        throw new Error(await res.text());
      }
      const json = (await res.json()) as AnalyticsOverview;
      setData(json);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, [API_BASE]);

  useEffect(() => {
    setLoading(true);
    fetchOnce();

    if (timerRef.current) {
      window.clearInterval(timerRef.current);
    }
    timerRef.current = window.setInterval(fetchOnce, pollMs);

    return () => {
      if (timerRef.current) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [fetchOnce, pollMs]);

  const hasData = useMemo(() => Boolean(data), [data]);

  return { data, loading, error, hasData, refresh: fetchOnce };
}
