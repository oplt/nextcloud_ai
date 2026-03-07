import React, { useEffect, useMemo, useState } from "react";
import Header from "../../../components/dashboard/Header";
import { IconButton, InputAdornment } from "@mui/material";
import Visibility from "@mui/icons-material/Visibility";
import VisibilityOff from "@mui/icons-material/VisibilityOff";

import {
  Alert,
  Box,
  Button,
  Container,
  Divider,
  FormControlLabel,
  Paper,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid";


type TelemetrySettings = {
  mqtt_broker: string;
  mqtt_port: number;
  mqtt_user: string;
  mqtt_pass?: string;
  mqtt_use_tls: boolean;
  mqtt_ca_certs: string;
  opcua_endpoint: string;
  opcua_security_policy: string;
  opcua_cert_path: string;
  opcua_key_path: string;
  telem_log_interval_sec: number;
  telemetry_topic: string;
};

type AISettings = {
    llm_provider: string;
    llm_api_base: string;
    llm_model: string;
    llm_api_key?: string;
};

type CredentialsSettings = {
    google_maps_api_key: string;
    drone_conn: string;
    admin_emails: string;
    admin_domains: string;
};

type HardwareSettings = {
      battery_capacity_wh: number;
      energy_reserve_frac: number;
      cruise_speed_mps: number;
      cruise_power_w: number;
      heartbeat_timeout: number;
      enforce_preflight_range: boolean;
};

type PreflightSettings = {
  HDOP_MAX: number;
  SAT_MIN: number;
  HOME_MAX_DIST: number;
  GPS_FIX_TYPE_MIN: number;
  EKF_THRESHOLD: number;
  COMPASS_HEALTH_REQUIRED: boolean;
  BATTERY_MIN_V: number;
  BATTERY_MIN_PERCENT: number;
  HEARTBEAT_MAX_AGE: number;
  MSG_RATE_MIN_HZ: number;
  RTL_MIN_ALT: number;
  MIN_CLEARANCE: number;
  AGL_MIN: number;
  AGL_MAX: number;
  MAX_RANGE_M: number;
  MAX_WAYPOINTS: number;
  NFZ_BUFFER_M: number;
  A_LAT_MAX: number;
  BANK_MAX_DEG: number;
  TURN_PENALTY_S: number;
  WP_RADIUS_M: number;
};

type RaspberrySettings = {
    raspberry_ip: string;
    raspberry_user: string;
    raspberry_host: string;
    raspberry_password?: string;
    ssh_key_path: string;
    raspberry_streaming_script_path: string;
};

type CameraSettings=  {
  drone_video_source: string;
  drone_video_source_gazebo: string;
  drone_video_use_gazebo: boolean;
  drone_video_width: number;
  drone_video_height: number;
  drone_video_fps: number;
  drone_video_timeout: number;
  drone_video_save_path: string;
  drone_video_fallback: string;
  drone_video_enabled: boolean;
  drone_video_save_stream: boolean;
};

type PhotogrammetrySettings = {
  PHOTOGRAMMETRY_DRONE_SYNC_DIR: string;
  PHOTOGRAMMETRY_DRONE_CAPTURE_STAGING_DIR: string;
  PHOTOGRAMMETRY_INPUTS_DIR: string;
  PHOTOGRAMMETRY_STORAGE_DIR: string;
  PHOTOGRAMMETRY_STORAGE_BASE_URL: string;
  PHOTOGRAMMETRY_3DTILES_CMD: string;
  PHOTOGRAMMETRY_ALLOW_MINIMAL_TILESET: boolean;
  WEBODM_BASE_URL: string;
  WEBODM_API_TOKEN?: string;
  WEBODM_PROJECT_ID: number;
  WEBODM_MOCK_MODE: boolean;
  MAPPING_JOB_QUEUE_BACKEND: string;
  CELERY_PHOTOGRAMMETRY_QUEUE: string;
  PHOTOGRAMMETRY_ASSET_SIGNING_SECRET?: string;
};

type AlertSettings = {
  enabled: boolean;
  check_interval_sec: number;
  dedupe_window_sec: number;
  operation_geofence_id?: number | null;
  monitor_herd_ids: string;
  herd_isolation_threshold_m: number;
  low_battery_percent: number;
  weak_link_percent: number;
  high_wind_mps: number;
  route_in_app: boolean;
  route_email: boolean;
  route_sms: boolean;
  email_recipients: string;
  sms_recipients: string;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password?: string;
  smtp_from: string;
  smtp_use_tls: boolean;
  twilio_account_sid: string;
  twilio_auth_token?: string;
  twilio_from_number: string;
};

type SettingsDoc = {
  telemetry: TelemetrySettings;
  ai: AISettings;
  credentials: CredentialsSettings;
  hardware: HardwareSettings;
  preflight: PreflightSettings;
  raspberry: RaspberrySettings;
  camera: CameraSettings;
  photogrammetry: PhotogrammetrySettings;
  alerts: AlertSettings;
  updated_at?: string;
};

type SettingsSection = Exclude<keyof SettingsDoc, "updated_at">;

const MASK = "********";

const DEFAULTS: SettingsDoc = {
  telemetry: {
    mqtt_broker: "localhost",
    mqtt_port: 1883,
    mqtt_user: "",
    mqtt_pass: "",
    mqtt_use_tls: false,
    mqtt_ca_certs: "",
    opcua_endpoint: "",
    opcua_security_policy: "",
    opcua_cert_path: "",
    opcua_key_path: "",
    telem_log_interval_sec: 2,
    telemetry_topic: "ardupilot/telemetry",
  },
  ai: {
    llm_provider: "ollama",
    llm_api_base: "",
    llm_model: "",
    llm_api_key: "",
  },
  credentials: {
    google_maps_api_key: "",
    drone_conn: "",
    admin_emails: "",
    admin_domains: "",
  },
  hardware: {
    battery_capacity_wh: 77,
    energy_reserve_frac: 0.2,
    cruise_speed_mps: 8,
    cruise_power_w: 180,
    heartbeat_timeout: 5,
    enforce_preflight_range: false,
  },
  preflight: {
    HDOP_MAX: 2,
    SAT_MIN: 10,
    HOME_MAX_DIST: 30,
    GPS_FIX_TYPE_MIN: 3,
    EKF_THRESHOLD: 0.8,
    COMPASS_HEALTH_REQUIRED: true,
    BATTERY_MIN_V: 0,
    BATTERY_MIN_PERCENT: 20,
    HEARTBEAT_MAX_AGE: 3,
    MSG_RATE_MIN_HZ: 2,
    RTL_MIN_ALT: 15,
    MIN_CLEARANCE: 3,
    AGL_MIN: 5,
    AGL_MAX: 120,
    MAX_RANGE_M: 1500,
    MAX_WAYPOINTS: 60,
    NFZ_BUFFER_M: 15,
    A_LAT_MAX: 3,
    BANK_MAX_DEG: 30,
    TURN_PENALTY_S: 2,
    WP_RADIUS_M: 2,
  },
  raspberry: {
    raspberry_ip: "",
    raspberry_user: "",
    raspberry_host: "",
    raspberry_password: "",
    ssh_key_path: "",
    raspberry_streaming_script_path: "",
  },
  camera: {
    drone_video_source: "",
    drone_video_source_gazebo: "udp://127.0.0.1:5600",
    drone_video_use_gazebo: false,
    drone_video_width: 640,
    drone_video_height: 480,
    drone_video_fps: 30,
    drone_video_timeout: 10,
    drone_video_save_path: "./backend/video/recordings/",
    drone_video_fallback: "",
    drone_video_enabled: true,
    drone_video_save_stream: false,
  },
  photogrammetry: {
    PHOTOGRAMMETRY_DRONE_SYNC_DIR: "backend/storage/drone_sync",
    PHOTOGRAMMETRY_DRONE_CAPTURE_STAGING_DIR: "backend/storage/staging",
    PHOTOGRAMMETRY_INPUTS_DIR: "backend/storage/mapping_jobs_inputs",
    PHOTOGRAMMETRY_STORAGE_DIR: "backend/storage/mapping",
    PHOTOGRAMMETRY_STORAGE_BASE_URL: "/mapping-assets",
    PHOTOGRAMMETRY_3DTILES_CMD: "",
    PHOTOGRAMMETRY_ALLOW_MINIMAL_TILESET: false,
    WEBODM_BASE_URL: "http://localhost:8001",
    WEBODM_API_TOKEN: "",
    WEBODM_PROJECT_ID: 1,
    WEBODM_MOCK_MODE: false,
    MAPPING_JOB_QUEUE_BACKEND: "celery",
    CELERY_PHOTOGRAMMETRY_QUEUE: "photogrammetry",
    PHOTOGRAMMETRY_ASSET_SIGNING_SECRET: "",
  },
  alerts: {
    enabled: true,
    check_interval_sec: 5,
    dedupe_window_sec: 300,
    operation_geofence_id: null,
    monitor_herd_ids: "",
    herd_isolation_threshold_m: 250,
    low_battery_percent: 25,
    weak_link_percent: 35,
    high_wind_mps: 12,
    route_in_app: true,
    route_email: false,
    route_sms: false,
    email_recipients: "",
    sms_recipients: "",
    smtp_host: "",
    smtp_port: 587,
    smtp_user: "",
    smtp_password: "",
    smtp_from: "",
    smtp_use_tls: true,
    twilio_account_sid: "",
    twilio_auth_token: "",
    twilio_from_number: "",
  },
  updated_at: undefined,
};

const normalizeDoc = (raw: Partial<SettingsDoc>): SettingsDoc => ({
  ...DEFAULTS,
  ...raw,
  telemetry: { ...DEFAULTS.telemetry, ...(raw.telemetry ?? {}) },
  ai: { ...DEFAULTS.ai, ...(raw.ai ?? {}) },
  credentials: { ...DEFAULTS.credentials, ...(raw.credentials ?? {}) },
  hardware: { ...DEFAULTS.hardware, ...(raw.hardware ?? {}) },
  preflight: { ...DEFAULTS.preflight, ...(raw.preflight ?? {}) },
  raspberry: { ...DEFAULTS.raspberry, ...(raw.raspberry ?? {}) },
  camera: { ...DEFAULTS.camera, ...(raw.camera ?? {}) },
  photogrammetry: { ...DEFAULTS.photogrammetry, ...(raw.photogrammetry ?? {}) },
  alerts: { ...DEFAULTS.alerts, ...(raw.alerts ?? {}) },
});

export default function SettingsPage() {
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [doc, setDoc] = useState<SettingsDoc>(DEFAULTS);
  const [lastLoaded, setLastLoaded] = useState<SettingsDoc>(DEFAULTS);

  const dirty = useMemo(() => JSON.stringify(doc) !== JSON.stringify(lastLoaded), [doc, lastLoaded]);

  const validateSettings = (): string | null => {
    if (doc.preflight.BATTERY_MIN_PERCENT < 10 || doc.preflight.BATTERY_MIN_PERCENT > 50) return "Battery Min (%) must be 10-50%.";
    if (doc.preflight.BANK_MAX_DEG > 45) return "Bank angle exceeds 45° safe limit.";
    return null;
  };

  const parseApiError = async (res: Response, fallback: string): Promise<string> => {
    try {
      const bodyText = await res.text();
      if (!bodyText.trim()) {
        return `${fallback} (${res.status})`;
      }
      const payload = JSON.parse(bodyText);
      if (typeof payload?.detail === "string" && payload.detail.trim()) {
        return payload.detail;
      }
      return bodyText;
    } catch {
      // ignore parse errors
    }
    return `${fallback} (${res.status})`;
  };

  async function fetchSettings() {
    setLoading(true); setErr(null);
    try {
      const res = await fetch("/api/settings");
      if (!res.ok) throw new Error(await parseApiError(res, "Failed to fetch settings"));
      const data = normalizeDoc(await res.json());
      setDoc(data); setLastLoaded(data);
    } catch (e: any) { setErr(e.message); } finally { setLoading(false); }
  }

  async function saveSettings() {
    const vErr = validateSettings();
    if (vErr) { setErr(vErr); return; }
    setSaving(true); setErr(null);
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        body: JSON.stringify(doc),
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error(await parseApiError(res, "Failed to save settings"));
      const saved = normalizeDoc(await res.json());
      setDoc(saved);
      setLastLoaded(saved);
    } catch (e: any) { setErr(e.message); } finally { setSaving(false); }
  }

  useEffect(() => { void fetchSettings(); }, []);

  const update = (section: SettingsSection, field: string, value: string | number | boolean | null) => {
    setDoc(prev => ({ ...prev, [section]: { ...prev[section], [field]: value } }));
    if (err) setErr(null);
  };

  const handleFileUpload = (section: SettingsSection, field: string) => async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      setErr(null);
      const formData = new FormData();
      formData.append("section", section);
      formData.append("field", field);
      formData.append("file", file);

      const res = await fetch("/api/settings/upload", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error(await parseApiError(res, "Failed to upload file"));
      const payload = await res.json();
      if (typeof payload?.path !== "string" || !payload.path) {
        throw new Error("Upload succeeded but no path was returned.");
      }
      update(section, field, payload.path);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      event.target.value = "";
    }
  };

function SecretField(props: React.ComponentProps<typeof TextField>) {
  const [show, setShow] = useState(false);
  return (
    <TextField variant="filled"
      {...props}
      type={show ? "text" : "password"}
      InputProps={{
        endAdornment: (
          <InputAdornment position="end">
            <IconButton
              onClick={() => setShow(v => !v)}
              onMouseDown={e => e.preventDefault()}
              edge="end"
              size="small"
              aria-label={show ? "Hide value" : "Show value"}
            >
              {show ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
            </IconButton>
          </InputAdornment>
        ),
      }}
    />
  );
}

  return (
    <>
      <Header />
      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Paper variant="outlined" sx={{ p: 0 }}>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto">
            <Tab label="Telemetry" />
            <Tab label="AI" />
            <Tab label="Credentials" />
            <Tab label="Hardware" />
            <Tab label="Preflight Check Params" />
            <Tab label="Alerts" />
            <Tab label="Raspberry" />
            <Tab label="Camera" />
            <Tab label="Photogrammetry" />
          </Tabs>
          <Divider />

          <Box sx={{ p: 3 }}>
            {err && <Alert severity="error" sx={{ mb: 2 }}>{err}</Alert>}
            {loading && <Alert severity="info" sx={{ mb: 2 }}>Loading settings...</Alert>}

            {/* TELEMETRY TAB */}
            {tab === 0 && (
              <Grid container spacing={3}>
                <Grid item size={{ xs: 12, md: 4 }} >
                  <Typography variant="h6" gutterBottom>MQTT Broker</Typography>
                  <Stack spacing={3}>
                    <TextField variant="filled" fullWidth label="Broker" value={doc.telemetry?.mqtt_broker} onChange={e => update("telemetry", "mqtt_broker", e.target.value)} />
                    <TextField variant="filled" fullWidth label="Port" type="number" value={doc.telemetry?.mqtt_port} onChange={e => update("telemetry", "mqtt_port", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="User" value={doc.telemetry?.mqtt_user} onChange={e => update("telemetry", "mqtt_user", e.target.value)} />
                    <SecretField fullWidth label="Password" placeholder={MASK} value={doc.telemetry?.mqtt_pass} onChange={e => update("telemetry", "mqtt_pass", e.target.value)} />
                    <FormControlLabel control={<Switch checked={doc.telemetry?.mqtt_use_tls} onChange={e => update("telemetry", "mqtt_use_tls", e.target.checked)} />} label="Use TLS" />

                      <Button variant="outlined" component="label" fullWidth>
                        Upload CA Certificate
                        <input type="file" hidden accept=".pem,.crt,.ca" onChange={handleFileUpload("telemetry", "mqtt_ca_certs")} />
                      </Button>
                      {doc.telemetry?.mqtt_ca_certs && <Typography variant="caption" display="block" sx={{ mt: 1 }}>✓ CA certificate uploaded</Typography>}
                    </Stack>
                </Grid>
                <Grid item size={{ xs: 12, md: 4 }}>
                  <Typography variant="h6" gutterBottom>OPC UA</Typography>
                  <Stack spacing={3}>
                    <TextField variant="filled" fullWidth label="Endpoint" value={doc.telemetry?.opcua_endpoint} onChange={e => update("telemetry", "opcua_endpoint", e.target.value)} />
                    <TextField variant="filled" fullWidth label="Security Policy" value={doc.telemetry?.opcua_security_policy} onChange={e => update("telemetry", "opcua_security_policy", e.target.value)} />

                      <Button variant="outlined" component="label" fullWidth>
                        Upload OPC UA Certificate
                        <input type="file" hidden accept=".pem,.crt,.cert" onChange={handleFileUpload("telemetry", "opcua_cert_path")} />
                      </Button>
                      {doc.telemetry?.opcua_cert_path && <Typography variant="caption" display="block" sx={{ mt: 1 }}>✓ Certificate uploaded</Typography>}

                      <Button variant="outlined" component="label" fullWidth>
                        Upload OPC UA Key
                        <input type="file" hidden accept=".pem,.key" onChange={handleFileUpload("telemetry", "opcua_key_path")} />
                      </Button>
                      {doc.telemetry?.opcua_key_path && <Typography variant="caption" display="block" sx={{ mt: 1 }}>✓ Key uploaded</Typography>}
                  </Stack>
                </Grid>
                <Grid item size={{ xs: 12, md: 4 }}>
                  <Typography variant="h6" gutterBottom>Logging & Topics</Typography>
                  <Stack spacing={3}>
                    <TextField variant="filled" fullWidth label="Log Interval (sec)" type="number" value={doc.telemetry?.telem_log_interval_sec} onChange={e => update("telemetry", "telem_log_interval_sec", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Telemetry Topic" value={doc.telemetry?.telemetry_topic} onChange={e => update("telemetry", "telemetry_topic", e.target.value)} />
                  </Stack>
              </Grid>
              </Grid>
            )}

            {/* AI TAB */}
            {tab === 1 && (
              <Grid container spacing={4}>
                <Grid item size={{ xs: 12, md: 6 }} >
                  <Typography variant="h6" gutterBottom>LLM Provider</Typography>
                   <Stack spacing={3}>
                    <TextField variant="filled" fullWidth label="Provider" value={doc.ai?.llm_provider} onChange={e => update("ai", "llm_provider", e.target.value)} />
                    <TextField variant="filled" fullWidth label="Model" value={doc.ai?.llm_model} onChange={e => update("ai", "llm_model", e.target.value)} />
                    <TextField variant="filled" fullWidth label="API Base" value={doc.ai?.llm_api_base} onChange={e => update("ai", "llm_api_base", e.target.value)} />
                    <SecretField fullWidth label="API Key"placeholder={MASK} value={doc.ai?.llm_api_key} onChange={e => update("ai", "llm_api_key", e.target.value)} />
                  </Stack>
                </Grid>

              </Grid>
            )}

            {/* CREDENTIALS TAB */}
            {tab === 2 && (
              <Grid container spacing={3}>
                <Grid item size={{ xs: 12, md: 6 }} >
                  <Typography variant="h6" gutterBottom>External APIs</Typography>
                   <Stack spacing={3}>
                    <SecretField fullWidth label="Google Maps API Key" value={doc.credentials?.google_maps_api_key} onChange={e => update("credentials", "google_maps_api_key", e.target.value)} />
                    <SecretField fullWidth label="Drone Connection String" value={doc.credentials?.drone_conn} onChange={e => update("credentials", "drone_conn", e.target.value)} />
                  </Stack>
                </Grid>
                <Grid item size={{ xs: 12, md: 6 }} >
                  <Typography variant="h6" gutterBottom>Administration</Typography>
                   <Stack spacing={3}>
                    <TextField variant="filled" fullWidth label="Admin Emails" value={doc.credentials?.admin_emails} onChange={e => update("credentials", "admin_emails", e.target.value)} />
                    <TextField variant="filled" fullWidth label="Admin Domains" value={doc.credentials?.admin_domains} onChange={e => update("credentials", "admin_domains", e.target.value)} />
                  </Stack>
                </Grid>
              </Grid>
            )}

            {/* HARDWARE TAB */}
            {tab === 3 && (
              <Grid container spacing={3}>
                <Grid item size={{ xs: 12, md: 6 }} >
                  <Typography variant="h6" gutterBottom>Drone</Typography>
                   <Stack spacing={3}>
                    <TextField variant="filled" fullWidth label="Battery Capacity (Wh)" type="number" value={doc.hardware?.battery_capacity_wh} onChange={e => update("hardware", "battery_capacity_wh", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Energy Reserve Fraction" type="number" inputProps={{ step: 0.1, min: 0, max: 1 }} value={doc.hardware?.energy_reserve_frac} onChange={e => update("hardware", "energy_reserve_frac", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Cruise Power (W)" type="number" value={doc.hardware?.cruise_power_w} onChange={e => update("hardware", "cruise_power_w", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Cruise Speed (mps)" type="number" value={doc.hardware?.cruise_speed_mps} onChange={e => update("hardware", "cruise_speed_mps", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Heartbeat Timeout" type="number" value={doc.hardware?.heartbeat_timeout} onChange={e => update("hardware", "heartbeat_timeout", Number(e.target.value))} />
                    <FormControlLabel control={<Switch checked={doc.hardware?.enforce_preflight_range} onChange={e => update("hardware", "enforce_preflight_range", e.target.checked)} />} label="Enforce Preflight Range" />
                  </Stack>
                </Grid>

              </Grid>
            )}

            {/* PREFLIGHT CHECK TAB */}
            {tab === 4 && (
              <Grid container spacing={4}>
                <Grid item size={{ xs: 12, md: 3 }} >
                  <Typography variant="h6" gutterBottom>GPS & Navigation</Typography>
                   <Stack spacing={3}>
                    <TextField variant="filled" fullWidth label="HDOP Max" type="number" value={doc.preflight?.HDOP_MAX} onChange={e => update("preflight", "HDOP_MAX", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Satellites Min" type="number" value={doc.preflight?.SAT_MIN} onChange={e => update("preflight", "SAT_MIN", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Home Max Dist (m)" type="number" value={doc.preflight?.HOME_MAX_DIST} onChange={e => update("preflight", "HOME_MAX_DIST", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="GPS Fix Type Min" type="number" value={doc.preflight?.GPS_FIX_TYPE_MIN} onChange={e => update("preflight", "GPS_FIX_TYPE_MIN", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="EKF Threshold" type="number" value={doc.preflight?.EKF_THRESHOLD} onChange={e => update("preflight", "EKF_THRESHOLD", Number(e.target.value))} />
                    <FormControlLabel control={<Switch checked={doc.preflight?.COMPASS_HEALTH_REQUIRED} onChange={e => update("preflight", "COMPASS_HEALTH_REQUIRED", e.target.checked)} />} label="Compass Health Required" />
                  </Stack>
                </Grid>
                <Grid item size={{ xs: 12, md: 3 }} >
                  <Typography variant="h6" gutterBottom>Battery & Heartbeat</Typography>
                   <Stack spacing={3}>
                    <TextField variant="filled" fullWidth label="Battery Min (V)" type="number" value={doc.preflight?.BATTERY_MIN_V} onChange={e => update("preflight", "BATTERY_MIN_V", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Battery Min %" type="number" value={doc.preflight?.BATTERY_MIN_PERCENT} onChange={e => update("preflight", "BATTERY_MIN_PERCENT", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Heartbeat Max Age" type="number" value={doc.preflight?.HEARTBEAT_MAX_AGE} onChange={e => update("preflight", "HEARTBEAT_MAX_AGE", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Msg Rate Min (Hz)" type="number" value={doc.preflight?.MSG_RATE_MIN_HZ} onChange={e => update("preflight", "MSG_RATE_MIN_HZ", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="RTL Min Alt (m)" type="number" value={doc.preflight?.RTL_MIN_ALT} onChange={e => update("preflight", "RTL_MIN_ALT", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Min Clearance (m)" type="number" value={doc.preflight?.MIN_CLEARANCE} onChange={e => update("preflight", "MIN_CLEARANCE", Number(e.target.value))} />
                  </Stack>
                </Grid>

                <Grid item size={{ xs: 12, md: 3 }} >
                  <Typography variant="h6" gutterBottom>Altitude & Range</Typography>
                   <Stack spacing={3}>
                    <TextField variant="filled" fullWidth label="AGL Min (m)" type="number" value={doc.preflight?.AGL_MIN} onChange={e => update("preflight", "AGL_MIN", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="AGL Max (m)" type="number" value={doc.preflight?.AGL_MAX} onChange={e => update("preflight", "AGL_MAX", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Max Range (m)" type="number" value={doc.preflight?.MAX_RANGE_M} onChange={e => update("preflight", "MAX_RANGE_M", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Max Waypoints" type="number" value={doc.preflight?.MAX_WAYPOINTS} onChange={e => update("preflight", "MAX_WAYPOINTS", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="NFZ Buffer (m)" type="number" value={doc.preflight?.NFZ_BUFFER_M} onChange={e => update("preflight", "NFZ_BUFFER_M", Number(e.target.value))} />
                  </Stack>
                </Grid>
                <Grid item size={{ xs: 12, md: 3 }} >
                  <Typography variant="h6" gutterBottom>Performance</Typography>
                  <Stack spacing={3}>
                    <TextField variant="filled" fullWidth label="A Lat Max" type="number" value={doc.preflight?.A_LAT_MAX} onChange={e => update("preflight", "A_LAT_MAX", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Bank Max (deg)" type="number" value={doc.preflight?.BANK_MAX_DEG} onChange={e => update("preflight", "BANK_MAX_DEG", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Turn Penalty (s)" type="number" value={doc.preflight?.TURN_PENALTY_S} onChange={e => update("preflight", "TURN_PENALTY_S", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="WP Radius (m)" type="number" value={doc.preflight?.WP_RADIUS_M} onChange={e => update("preflight", "WP_RADIUS_M", Number(e.target.value))} />
                  </Stack>
                </Grid>
              </Grid>
            )}

            {/* ALERTS TAB */}
            {tab === 5 && (
              <Grid container spacing={3}>
                <Grid item size={{ xs: 12, md: 6 }}>
                  <Typography variant="h6" gutterBottom>Rules</Typography>
                  <Stack spacing={3}>
                    <FormControlLabel
                      control={<Switch checked={doc.alerts?.enabled} onChange={e => update("alerts", "enabled", e.target.checked)} />}
                      label="Enable Alert Engine"
                    />
                    <TextField variant="filled" fullWidth label="Check Interval (sec)" type="number" value={doc.alerts?.check_interval_sec} onChange={e => update("alerts", "check_interval_sec", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Dedupe Window (sec)" type="number" value={doc.alerts?.dedupe_window_sec} onChange={e => update("alerts", "dedupe_window_sec", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Operation Geofence ID" type="number" value={doc.alerts?.operation_geofence_id ?? ""} onChange={e => update("alerts", "operation_geofence_id", e.target.value ? Number(e.target.value) : null)} />
                    <TextField variant="filled" fullWidth label="Monitor Herd IDs (comma-separated)" value={doc.alerts?.monitor_herd_ids} onChange={e => update("alerts", "monitor_herd_ids", e.target.value)} />
                    <TextField variant="filled" fullWidth label="Herd Isolation Threshold (m)" type="number" value={doc.alerts?.herd_isolation_threshold_m} onChange={e => update("alerts", "herd_isolation_threshold_m", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Low Battery Threshold (%)" type="number" value={doc.alerts?.low_battery_percent} onChange={e => update("alerts", "low_battery_percent", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Weak Link Threshold (%)" type="number" value={doc.alerts?.weak_link_percent} onChange={e => update("alerts", "weak_link_percent", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="High Wind Threshold (m/s)" type="number" value={doc.alerts?.high_wind_mps} onChange={e => update("alerts", "high_wind_mps", Number(e.target.value))} />
                  </Stack>
                </Grid>
                <Grid item size={{ xs: 12, md: 6 }}>
                  <Typography variant="h6" gutterBottom>Routing & Channels</Typography>
                  <Stack spacing={3}>
                    <FormControlLabel
                      control={<Switch checked={doc.alerts?.route_in_app} onChange={e => update("alerts", "route_in_app", e.target.checked)} />}
                      label="Route In-App"
                    />
                    <FormControlLabel
                      control={<Switch checked={doc.alerts?.route_email} onChange={e => update("alerts", "route_email", e.target.checked)} />}
                      label="Route Email"
                    />
                    <TextField variant="filled" fullWidth label="Email Recipients" value={doc.alerts?.email_recipients} onChange={e => update("alerts", "email_recipients", e.target.value)} />
                    <TextField variant="filled" fullWidth label="SMTP Host" value={doc.alerts?.smtp_host} onChange={e => update("alerts", "smtp_host", e.target.value)} />
                    <TextField variant="filled" fullWidth label="SMTP Port" type="number" value={doc.alerts?.smtp_port} onChange={e => update("alerts", "smtp_port", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="SMTP User" value={doc.alerts?.smtp_user} onChange={e => update("alerts", "smtp_user", e.target.value)} />
                    <SecretField fullWidth label="SMTP Password" placeholder={MASK} value={doc.alerts?.smtp_password} onChange={e => update("alerts", "smtp_password", e.target.value)} />
                    <TextField variant="filled" fullWidth label="SMTP From Address" value={doc.alerts?.smtp_from} onChange={e => update("alerts", "smtp_from", e.target.value)} />
                    <FormControlLabel
                      control={<Switch checked={doc.alerts?.smtp_use_tls} onChange={e => update("alerts", "smtp_use_tls", e.target.checked)} />}
                      label="SMTP TLS"
                    />
                    <FormControlLabel
                      control={<Switch checked={doc.alerts?.route_sms} onChange={e => update("alerts", "route_sms", e.target.checked)} />}
                      label="Route SMS"
                    />
                    <TextField variant="filled" fullWidth label="SMS Recipients" value={doc.alerts?.sms_recipients} onChange={e => update("alerts", "sms_recipients", e.target.value)} />
                    <TextField variant="filled" fullWidth label="Twilio Account SID" value={doc.alerts?.twilio_account_sid} onChange={e => update("alerts", "twilio_account_sid", e.target.value)} />
                    <SecretField fullWidth label="Twilio Auth Token" placeholder={MASK} value={doc.alerts?.twilio_auth_token} onChange={e => update("alerts", "twilio_auth_token", e.target.value)} />
                    <TextField variant="filled" fullWidth label="Twilio From Number" value={doc.alerts?.twilio_from_number} onChange={e => update("alerts", "twilio_from_number", e.target.value)} />
                  </Stack>
                </Grid>
              </Grid>
            )}

            {/* RASPBERRY TAB */}
            {tab === 6 && (
                <Grid container spacing={3}>
                <Grid item size={{ xs: 12, md: 6 }} >
                  <Typography variant="h6" gutterBottom>Raspberry Pi Connection</Typography>
                   <Stack spacing={3}>
                    <SecretField fullWidth label="IP Address" value={doc.raspberry?.raspberry_ip} onChange={e => update("raspberry", "raspberry_ip", e.target.value)} />
                    <TextField variant="filled" fullWidth label="Hostname" value={doc.raspberry?.raspberry_host} onChange={e => update("raspberry", "raspberry_host", e.target.value)} />
                    <TextField variant="filled" fullWidth label="Username" value={doc.raspberry?.raspberry_user} onChange={e => update("raspberry", "raspberry_user", e.target.value)} />
                    <SecretField fullWidth label="Password" placeholder={MASK} value={doc.raspberry?.raspberry_password} onChange={e => update("raspberry", "raspberry_password", e.target.value)} />
                    <SecretField fullWidth label="Streaming Script Path" value={doc.raspberry?.raspberry_streaming_script_path} onChange={e => update("raspberry", "raspberry_streaming_script_path", e.target.value)} />

                      <Button variant="outlined" component="label" fullWidth>
                        Upload SSH Key
                        <input type="file" hidden accept=".pem,.key,.pub" onChange={handleFileUpload("raspberry", "ssh_key_path")} />
                      </Button>
                      {doc.raspberry?.ssh_key_path && <Typography variant="caption" display="block" sx={{ mt: 1 }}>✓ SSH key uploaded</Typography>}

                  </Stack>
                </Grid>
                </Grid>
            )}


            {/* CAMERA TAB */}
            {tab === 7 && (
              <Grid container spacing={3}>
                <Grid item size={{ xs: 12, md: 6 }}>
                  <Typography variant="h6" gutterBottom>Drone Camera Parameters</Typography>
                  <Stack spacing={3}>
                    <SecretField fullWidth label="Camera Source" value={doc.camera?.drone_video_source} onChange={e => update("camera", "drone_video_source", e.target.value)} />
                    <SecretField fullWidth label="Gazebo Camera Source" value={doc.camera?.drone_video_source_gazebo} onChange={e => update("camera", "drone_video_source_gazebo", e.target.value)} />
                    <TextField variant="filled" fullWidth label="Width" type="number" value={doc.camera?.drone_video_width} onChange={e => update("camera", "drone_video_width", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Height" type="number" value={doc.camera?.drone_video_height} onChange={e => update("camera", "drone_video_height", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="FPS" type="number" value={doc.camera?.drone_video_fps} onChange={e => update("camera", "drone_video_fps", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Timeout" type="number" value={doc.camera?.drone_video_timeout} onChange={e => update("camera", "drone_video_timeout", Number(e.target.value))} />
                    <TextField variant="filled" fullWidth label="Fallback" value={doc.camera?.drone_video_fallback} onChange={e => update("camera", "drone_video_fallback", e.target.value)} />

                    <Stack direction="row" spacing={25}>
                      <FormControlLabel
                        control={<Switch checked={doc.camera?.drone_video_enabled} onChange={e => update("camera", "drone_video_enabled", e.target.checked)} />}
                        label="Enable Stream"
                      />
                      <FormControlLabel
                        control={<Switch checked={doc.camera?.drone_video_save_stream} onChange={e => update("camera", "drone_video_save_stream", e.target.checked)} />}
                        label="Save Stream"
                      />
                      <FormControlLabel
                        control={<Switch checked={doc.camera?.drone_video_use_gazebo} onChange={e => update("camera", "drone_video_use_gazebo", e.target.checked)} />}
                        label="Use Gazebo"
                      />
                    </Stack>
                  </Stack>
                </Grid>
              </Grid>
            )}

            {/* PHOTOGRAMMETRY TAB */}
            {tab === 8 && (
              <Grid container spacing={3}>
                <Grid item size={{ xs: 12, md: 6 }}>
                  <Typography variant="h6" gutterBottom>Storage & Sync</Typography>
                  <Stack spacing={3}>
                    <TextField
                      variant="filled"
                      fullWidth
                      label="Drone Sync Dir"
                      placeholder={DEFAULTS.photogrammetry.PHOTOGRAMMETRY_DRONE_SYNC_DIR}
                      value={doc.photogrammetry?.PHOTOGRAMMETRY_DRONE_SYNC_DIR}
                      onChange={e => update("photogrammetry", "PHOTOGRAMMETRY_DRONE_SYNC_DIR", e.target.value)}
                    />
                    <TextField
                      variant="filled"
                      fullWidth
                      label="Capture Staging Dir"
                      placeholder={DEFAULTS.photogrammetry.PHOTOGRAMMETRY_DRONE_CAPTURE_STAGING_DIR}
                      value={doc.photogrammetry?.PHOTOGRAMMETRY_DRONE_CAPTURE_STAGING_DIR}
                      onChange={e => update("photogrammetry", "PHOTOGRAMMETRY_DRONE_CAPTURE_STAGING_DIR", e.target.value)}
                    />
                    <TextField
                      variant="filled"
                      fullWidth
                      label="Inputs Dir"
                      placeholder={DEFAULTS.photogrammetry.PHOTOGRAMMETRY_INPUTS_DIR}
                      value={doc.photogrammetry?.PHOTOGRAMMETRY_INPUTS_DIR}
                      onChange={e => update("photogrammetry", "PHOTOGRAMMETRY_INPUTS_DIR", e.target.value)}
                    />
                    <TextField
                      variant="filled"
                      fullWidth
                      label="Storage Dir"
                      placeholder={DEFAULTS.photogrammetry.PHOTOGRAMMETRY_STORAGE_DIR}
                      value={doc.photogrammetry?.PHOTOGRAMMETRY_STORAGE_DIR}
                      onChange={e => update("photogrammetry", "PHOTOGRAMMETRY_STORAGE_DIR", e.target.value)}
                    />
                    <TextField
                      variant="filled"
                      fullWidth
                      label="Storage Base URL"
                      placeholder={DEFAULTS.photogrammetry.PHOTOGRAMMETRY_STORAGE_BASE_URL}
                      value={doc.photogrammetry?.PHOTOGRAMMETRY_STORAGE_BASE_URL}
                      onChange={e => update("photogrammetry", "PHOTOGRAMMETRY_STORAGE_BASE_URL", e.target.value)}
                    />
                    <TextField
                      variant="filled"
                      fullWidth
                      label="3D Tiles Command"
                      placeholder="(none)"
                      value={doc.photogrammetry?.PHOTOGRAMMETRY_3DTILES_CMD}
                      onChange={e => update("photogrammetry", "PHOTOGRAMMETRY_3DTILES_CMD", e.target.value)}
                    />
                    <FormControlLabel
                      control={
                        <Switch
                          checked={doc.photogrammetry?.PHOTOGRAMMETRY_ALLOW_MINIMAL_TILESET}
                          onChange={e => update("photogrammetry", "PHOTOGRAMMETRY_ALLOW_MINIMAL_TILESET", e.target.checked)}
                        />
                      }
                      label="Allow Minimal Tileset (Dev)"
                    />
                  </Stack>
                </Grid>

                <Grid item size={{ xs: 12, md: 6 }}>
                  <Typography variant="h6" gutterBottom>WebODM & Queue</Typography>
                  <Stack spacing={3}>
                    <TextField
                      variant="filled"
                      fullWidth
                      label="WebODM Base URL"
                      placeholder={DEFAULTS.photogrammetry.WEBODM_BASE_URL}
                      value={doc.photogrammetry?.WEBODM_BASE_URL}
                      onChange={e => update("photogrammetry", "WEBODM_BASE_URL", e.target.value)}
                    />
                    <SecretField
                      fullWidth
                      label="WebODM API Token"
                      placeholder="(none)"
                      value={doc.photogrammetry?.WEBODM_API_TOKEN}
                      onChange={e => update("photogrammetry", "WEBODM_API_TOKEN", e.target.value)}
                    />
                    <TextField
                      variant="filled"
                      fullWidth
                      type="number"
                      label="WebODM Project ID"
                      placeholder={String(DEFAULTS.photogrammetry.WEBODM_PROJECT_ID)}
                      value={doc.photogrammetry?.WEBODM_PROJECT_ID}
                      onChange={e => update("photogrammetry", "WEBODM_PROJECT_ID", Number(e.target.value))}
                    />
                    <FormControlLabel
                      control={
                        <Switch
                          checked={doc.photogrammetry?.WEBODM_MOCK_MODE}
                          onChange={e => update("photogrammetry", "WEBODM_MOCK_MODE", e.target.checked)}
                        />
                      }
                      label="WebODM Mock Mode"
                    />
                    <TextField
                      variant="filled"
                      fullWidth
                      label="Mapping Job Queue Backend"
                      placeholder={DEFAULTS.photogrammetry.MAPPING_JOB_QUEUE_BACKEND}
                      value={doc.photogrammetry?.MAPPING_JOB_QUEUE_BACKEND}
                      onChange={e => update("photogrammetry", "MAPPING_JOB_QUEUE_BACKEND", e.target.value)}
                    />
                    <TextField
                      variant="filled"
                      fullWidth
                      label="Celery Photogrammetry Queue"
                      placeholder={DEFAULTS.photogrammetry.CELERY_PHOTOGRAMMETRY_QUEUE}
                      value={doc.photogrammetry?.CELERY_PHOTOGRAMMETRY_QUEUE}
                      onChange={e => update("photogrammetry", "CELERY_PHOTOGRAMMETRY_QUEUE", e.target.value)}
                    />
                    <SecretField
                      fullWidth
                      label="Asset Signing Secret"
                      placeholder="(uses jwt_secret)"
                      value={doc.photogrammetry?.PHOTOGRAMMETRY_ASSET_SIGNING_SECRET}
                      onChange={e => update("photogrammetry", "PHOTOGRAMMETRY_ASSET_SIGNING_SECRET", e.target.value)}
                    />
                  </Stack>
                </Grid>
              </Grid>
            )}



            <Box sx={{ mt: 4, display: "flex", justifyContent: "flex-end", gap: 2 }}>
              <Button onClick={fetchSettings} disabled={loading || saving} variant="outlined">Reset</Button>
              <Button disabled={!dirty || saving || loading} onClick={saveSettings} variant="contained">
                {saving ? "Saving..." : "Save All Changes"}
              </Button>
            </Box>
          </Box>
        </Paper>
      </Container>
    </>
  );
}
