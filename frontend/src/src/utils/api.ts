
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {},
  token: string | null = null
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint.startsWith("/") ? endpoint : "/" + endpoint}`;

  const headers = new Headers(options.headers ?? {});
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.message || `Request failed with status ${response.status}`);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

export type PreflightRunResponse = {
  preflight_run_id: string;
  mission_fingerprint?: string;
  overall_status: string;
  can_start_mission: boolean;
  created_at?: number;
  expires_at?: number;
  report?: {
    mission_type?: string;
    overall_status?: string;
    base_checks?: Array<{
      name: string;
      status: string;
      message?: string | null;
    }>;
    mission_checks?: Array<{
      name: string;
      status: string;
      message?: string | null;
    }>;
    summary?: {
      failed?: number;
      warned?: number;
      passed?: number;
      total_checks?: number;
    };
  };
};

export type MissionLifecycleState =
  | "queued"
  | "running"
  | "paused"
  | "aborted"
  | "completed"
  | "failed";

export type MissionCommand = "pause" | "resume" | "abort";

export type MissionRuntimeResponse = {
  flight_id: string;
  mission_name: string;
  mission_type: string;
  state: MissionLifecycleState;
  created_at: number;
  updated_at: number;
  preflight_run_id?: string | null;
  db_flight_id?: string | null;
  last_error?: string | null;
};

export type MissionCreateResponse = {
  flight_id: string;
  status: string;
  mission_name: string;
  mission_type: string;
  waypoints_count: number;
  preflight_run_id?: string | null;
};

export type MissionCommandResponse = {
  flight_id: string;
  command_id: string;
  command: MissionCommand;
  idempotency_key: string;
  state_before: MissionLifecycleState;
  state_after: MissionLifecycleState;
  accepted: boolean;
  message: string;
  requested_at: number;
};

export type MissionCommandAuditResponse = {
  command_id: string;
  command: MissionCommand;
  idempotency_key: string;
  requested_by_user_id: number;
  requested_at: number;
  state_before: MissionLifecycleState;
  state_after: MissionLifecycleState;
  accepted: boolean;
  message: string;
  reason?: string | null;
};

const parseErrorText = (bodyText: string): string => {
  const trimmed = bodyText.trim();
  if (!trimmed) return "";
  try {
    const parsed = JSON.parse(trimmed);
    const detail = parsed?.detail ?? parsed?.message ?? parsed?.error;
    if (typeof detail === "string" && detail.trim()) {
      return detail.trim();
    }
  } catch {
    // keep raw text fallback
  }
  return trimmed;
};

const readErrorMessage = async (response: Response): Promise<string> => {
  const bodyText = await response.text().catch(() => "");
  const parsed = parseErrorText(bodyText);
  if (parsed) return parsed;
  return `Request failed with status ${response.status}`;
};

export async function startMissionWithPreflight(
  missionPayload: Record<string, unknown>,
  token: string,
  apiBase: string = API_BASE_URL,
): Promise<{ preflight: PreflightRunResponse; mission: MissionCreateResponse }> {
  const normalizedBase = apiBase.replace(/\/$/, "");
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };

  const preflightRes = await fetch(`${normalizedBase}/tasks/preflight/run`, {
    method: "POST",
    headers,
    body: JSON.stringify(missionPayload),
  });
  if (!preflightRes.ok) {
    throw new Error(await readErrorMessage(preflightRes));
  }

  const preflight = (await preflightRes.json()) as PreflightRunResponse;
  if (!preflight?.preflight_run_id) {
    throw new Error("Preflight run did not return a run id.");
  }
  if (!preflight.can_start_mission) {
    const failed = preflight.report?.summary?.failed;
    const status = preflight.overall_status || "FAIL";
    throw new Error(
      typeof failed === "number"
        ? `Preflight ${status}. ${failed} checks failed; mission start blocked.`
        : `Preflight ${status}. Mission start blocked.`,
    );
  }

  const missionRes = await fetch(`${normalizedBase}/tasks/missions`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      ...missionPayload,
      preflight_run_id: preflight.preflight_run_id,
    }),
  });
  if (!missionRes.ok) {
    throw new Error(await readErrorMessage(missionRes));
  }

  const mission = (await missionRes.json()) as MissionCreateResponse;
  return { preflight, mission };
}

export async function getMissionRuntime(
  flightId: string,
  token: string,
  apiBase: string = API_BASE_URL,
): Promise<MissionRuntimeResponse> {
  const normalizedBase = apiBase.replace(/\/$/, "");
  const res = await fetch(`${normalizedBase}/tasks/missions/${encodeURIComponent(flightId)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }
  return res.json();
}

export async function sendMissionCommand(
  flightId: string,
  command: MissionCommand,
  token: string,
  idempotencyKey: string,
  reason?: string,
  apiBase: string = API_BASE_URL,
): Promise<MissionCommandResponse> {
  const normalizedBase = apiBase.replace(/\/$/, "");
  const res = await fetch(
    `${normalizedBase}/tasks/missions/${encodeURIComponent(flightId)}/commands/${command}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({
        idempotency_key: idempotencyKey,
        reason: reason ?? null,
      }),
    },
  );
  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }
  return res.json();
}

export async function getMissionCommandAudit(
  flightId: string,
  token: string,
  apiBase: string = API_BASE_URL,
): Promise<MissionCommandAuditResponse[]> {
  const normalizedBase = apiBase.replace(/\/$/, "");
  const res = await fetch(
    `${normalizedBase}/tasks/missions/${encodeURIComponent(flightId)}/commands`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }
  return res.json();
}
