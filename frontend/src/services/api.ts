// 📁 LOCATION: frontend/src/services/api.ts
import axios from "axios";

let rawBase = (process.env.NEXT_PUBLIC_API_URL || "").trim();

// When running in the browser on Render, automatically route to Render backend if not explicitly set or set to localhost
if (typeof window !== "undefined" && window.location.hostname.endsWith(".onrender.com")) {
  if (!rawBase || rawBase.includes("localhost") || rawBase.includes("127.0.0.1")) {
    rawBase = "https://cognisphere-backend-ya2y.onrender.com";
  }
}

if (!rawBase) {
  rawBase = "http://localhost:8000";
}

// Normalize Render internal service name or missing FQDN (e.g. "cognisphere-backend-ya2y" -> "https://cognisphere-backend-ya2y.onrender.com")
if (!rawBase.includes(".") && !rawBase.startsWith("localhost") && !rawBase.startsWith("127.0.0.1") && !rawBase.includes(":")) {
  rawBase = `${rawBase}.onrender.com`;
}

if (!rawBase.startsWith("http://") && !rawBase.startsWith("https://")) {
  rawBase = (rawBase.startsWith("localhost") || rawBase.startsWith("127.0.0.1"))
    ? `http://${rawBase}`
    : `https://${rawBase}`;
}

export const API_BASE_URL = rawBase.replace(/\/+$/, "");

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
  withCredentials: true,
});

const AUTH_TOKEN_KEY = "cognisphere_auth_token";

let _inMemoryToken: string | null = null;
if (typeof window !== "undefined") {
  try {
    _inMemoryToken = localStorage.getItem(AUTH_TOKEN_KEY);
  } catch {
    _inMemoryToken = null;
  }
}

export const setAuthToken = (token: string | null) => {
  _inMemoryToken = token;
  if (typeof window !== "undefined") {
    try {
      if (token) {
        localStorage.setItem(AUTH_TOKEN_KEY, token);
      } else {
        localStorage.removeItem(AUTH_TOKEN_KEY);
      }
    } catch {
      // localStorage may be restricted in private browsing
    }
  }
};

export const getAuthToken = (): string | null => {
  if (!_inMemoryToken && typeof window !== "undefined") {
    try {
      _inMemoryToken = localStorage.getItem(AUTH_TOKEN_KEY);
    } catch {
      _inMemoryToken = null;
    }
  }
  return _inMemoryToken;
};

api.interceptors.request.use((config) => {
  const token = getAuthToken();
  if (token && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Auth Types & Methods ──────────────────────────────────────────────────────

export interface UserProfile {
  id:          number;
  email:       string;
  created_at?: string;
  updated_at?: string;
}

export interface AuthResponse {
  status:  string;
  message: string;
  user:    UserProfile;
  token:   string;
}

export const registerUser = async (email: string, password: string): Promise<AuthResponse> => {
  const res = await api.post<AuthResponse>("/auth/register", { email, password });
  if (res.data.token) setAuthToken(res.data.token);
  return res.data;
};

export const loginUser = async (email: string, password: string): Promise<AuthResponse> => {
  const res = await api.post<AuthResponse>("/auth/login", { email, password });
  if (res.data.token) setAuthToken(res.data.token);
  return res.data;
};

export const logoutUser = async (): Promise<void> => {
  try {
    await api.post("/auth/logout");
  } finally {
    setAuthToken(null);
  }
};

export const getMe = async (): Promise<UserProfile> => {
  const res = await api.get<UserProfile>("/auth/me");
  return res.data;
};

export const changeUserPassword = async (currentPassword: string, newPassword: string) => {
  const res = await api.post("/auth/change-password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
  return res.data;
};

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Memory {
  id:               number;
  title:            string;
  description:      string;
  source:           string;
  file_type:        string;
  image:            string | null;
  date:             string | null;
  location:         string | null;
  objects:          string[];
  importance_score: number;
  access_count:     number;
  version?:         number;
  parent_id?:       number | null;
  goals?:           Goal[];
  // ACMA fields (present in search results)
  activation_score?:   number;
  activation_reason?:  string;
  matched_goals?:      string[];
  components?: {
    semantic:     number;
    goal:         number;
    relationship: number;
    importance:   number;
    temporal:     number;
    access:       number;
    title_boost?: number;
  };
}

export interface MemoryHistoryEntry {
  id:               number;
  memory_id:        number;
  version:          number;
  title:            string;
  description:      string;
  importance_score: number;
  source:           string;
  file_type:        string;
  date:             string | null;
  archived_at:      string | null;
  change_reason:    string;
}

export interface Goal {
  id:          number;
  name:        string;
  description: string;
  status:      string;
  progress:    number;
  parent_id:   number | null;
}

export interface SearchResult {
  query:   string;
  mode:    string;
  count:   number;
  results: Memory[];
}

export interface MemorySource {
  memory_id:       number;
  title:           string;
  file_type:       string;
  source:          string;       // original filename
  file_path:       string;       // full OS path or best available address
  abstract:        string;       // 1-3 sentence clean summary
  relevance_score: number;
  timestamp:       string;
  image:           string;
}

export interface ChatResponse {
  answer:        string;
  session_id?:   string;
  intent?:       string;
  confidence?:   number;
  fast_answer?:  boolean;        // true if answered without Ollama
  memories_used: { id: number; title: string; activation_score: number; activation_reason: string; matched_goals?: string[]; components?: Memory["components"] }[];
  goal_context:  string[];
  sources:       MemorySource[]; // enriched sources with file_path + abstract
  plan?:         Record<string, any>;
}

export interface GoalProgress {
  goal:            Goal;
  total_memories:  number;
  present:         { id: number; title: string; date: string }[];
  missing_hints:   string[];
  completion_pct:  number;
}

export interface Trajectory {
  goal_name:                 string;
  sequence:                  { document: string; acquired: boolean; acquired_date: string | null; expected_order: number }[];
  velocity_days_per_doc:     number | null;
  next_recommended:          string | null;
  projected_completion_date: string | null;
  confidence:                number;
}

export interface Stats {
  totals:           { memories: number; goals: number; goal_memory_edges: number };
  goals:            { by_status: Record<string, number>; active: number; completed: number };
  files:            { by_type: Record<string, number>; embedding_coverage: string; object_detection_coverage: string };
  acma:             { avg_importance_score: number; total_retrievals: number; most_accessed: { id: number; title: string; access_count: number }[] };
  recent_memories:  { id: number; title: string; date: string }[];
}

export interface ExperimentConfig {
  query:             string;
  use_faiss?:        boolean;
  use_bm25?:         boolean;
  use_title?:        boolean;
  use_rrf?:          boolean;
  use_acma?:         boolean;
  acma_goal?:        boolean;
  acma_relationship?: boolean;
  acma_importance?:  boolean;
  acma_temporal?:    boolean;
  acma_access?:      boolean;
  acma_title_boost?: boolean;
  weight_semantic?:      number | null;
  weight_goal?:          number | null;
  weight_relationship?:  number | null;
  weight_importance?:    number | null;
  weight_temporal?:      number | null;
  weight_access?:        number | null;
  top_k?:            number;
}

export interface ExperimentResult {
  config:        ExperimentConfig;
  faiss_results: any[];
  bm25_results:  any[];
  title_results: any[];
  rrf_results:   any[];
  acma_results:  Memory[];
}

// ── Search ────────────────────────────────────────────────────────────────────

export const checkHealth = () => api.get("/health").then(r => r.data);

export const searchMemories = (q: string, mode = "acma", top_k = 10) =>
  api.get<SearchResult>("/search/", { params: { q, mode, top_k } }).then(r => r.data);

export const searchContent = searchMemories;

export const explainActivation = (memory_id: number, q: string) =>
  api.get(`/search/explain/${memory_id}`, { params: { q } }).then(r => r.data);

// ── Memories ──────────────────────────────────────────────────────────────────

export const getMemories    = ()   => api.get<Memory[]>("/memories/").then(r => r.data);
export const getMemory      = (id: number) => api.get<Memory>(`/memories/${id}`).then(r => r.data);
export const deleteMemory   = (id: number) => api.delete(`/memories/${id}`).then(r => r.data);
export const getRelated     = (id: number) => api.get(`/memory-details/${id}/related`).then(r => r.data);

export const createMemory = (payload: {
  title: string;
  description: string;
  importance_score?: number;
  source?: string;
  date?: string;
}) => api.post("/memories/", payload).then(r => r.data);

export const updateMemory = (id: number, payload: {
  title?: string;
  description?: string;
  importance_score?: number;
  date?: string;
  change_reason?: string;
}) => api.put(`/memories/${id}/update`, payload).then(r => r.data);

export const getMemoryHistory = (id: number) =>
  api.get(`/memories/${id}/history`).then(r => r.data);

export const updateImportance = (id: number, importance_score: number) =>
  api.patch(`/memories/${id}/importance`, { importance_score }).then(r => r.data);

// ── Upload & Job Polling ──────────────────────────────────────────────────────

export interface JobStatusResponse {
  job_id:           string;
  filename:         string;
  status:           "pending" | "processing" | "completed" | "failed";
  stage:            string;
  message?:         string;
  memory_id?:       number;
  memory?:          any;
  error?:           string;
  processing_time?: number;
  created_at?:      string;
  updated_at?:      string;
}

export const getJobStatus = async (jobId: string): Promise<JobStatusResponse> => {
  try {
    const res = await api.get<JobStatusResponse>(`/upload/status/${jobId}`);
    return res.data;
  } catch {
    const res = await api.get<JobStatusResponse>(`/status/${jobId}`);
    return res.data;
  }
};

export const pollJobStatus = async (
  jobId: string,
  onProgress?: (stage: string, message: string) => void,
  timeoutMs: number = 90000
): Promise<any> => {
  const startTime = Date.now();
  const pollInterval = 1200;

  while (Date.now() - startTime < timeoutMs) {
    try {
      const job = await getJobStatus(jobId);
      if (onProgress && (job.stage || job.message)) {
        onProgress(job.stage, job.message || "");
      }

      if (job.status === "completed") {
        return job.memory || { id: job.memory_id, source: job.filename };
      }

      if (job.status === "failed") {
        throw new Error(job.error || job.message || "Document processing failed");
      }
    } catch (err: any) {
      if (err.message && !err.response) {
        throw err;
      }
      console.warn(`[Job Poll] Retrying poll for job ${jobId}...`);
    }

    await new Promise(resolve => setTimeout(resolve, pollInterval));
  }

  throw new Error("Document processing timed out after 90 seconds");
};

export const uploadFile = async (
  file: File,
  onProgress?: (stage: string, message: string) => void
) => {
  const form = new FormData();
  form.append("file", file);
  const res = await api.post("/upload/", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });

  const data = res.data;

  // Immediate legacy response support
  if (data.success && data.memory) {
    return data.memory;
  }

  // Asynchronous job support (HTTP 202)
  if (data.job_id) {
    if (onProgress) {
      onProgress("processing", data.message || "Processing started");
    }
    return await pollJobStatus(data.job_id, onProgress);
  }

  return data;
};

// ── Chat ──────────────────────────────────────────────────────────────────────

export const sendChat = async (
  query: string,
  session_id?: string,
  history?: any[]
) => {
  try {
    const res = await api.post<ChatResponse>("/chat/", {
      query,
      session_id,
      history,
    });

    return res.data;
  } catch (err: any) {
    console.error("CHAT ERROR:", err.response?.data);
    console.error(err);

    throw err;
  }
};

export const getChatHistory = (session_id: string) =>
  api.get(`/chat/history/${session_id}`).then(r => r.data);

// ── Goals ─────────────────────────────────────────────────────────────────────

export const getGoals       = ()              => api.get<Goal[]>("/goals/").then(r => r.data);
export const createGoal     = (name: string, description: string) =>
  api.post("/goals/", { name, description }).then(r => r.data);
export const getGoalProgress = (id: number)  => api.get<GoalProgress>(`/goals/${id}/progress`).then(r => r.data);
export const updateGoalStatus = (id: number, status: string) =>
  api.patch(`/goals/${id}/status`, { status }).then(r => r.data);
export const deleteGoal = (id: number) => api.delete(`/goals/${id}`).then(r => r.data);

// ── Trajectories ──────────────────────────────────────────────────────────────

export const getTrajectories = () => api.get<{ trajectories: Trajectory[] }>("/trajectories/").then(r => r.data);
export const getTrajectory   = (id: number) => api.get<Trajectory>(`/trajectories/${id}`).then(r => r.data);

// ── Timeline ──────────────────────────────────────────────────────────────────

export const getTimeline = (limit = 100) => api.get("/timeline/", { params: { limit } }).then(r => r.data);
export const getRecent   = (limit = 20)  => api.get("/timeline/recent", { params: { limit } }).then(r => r.data);

// ── Stats ─────────────────────────────────────────────────────────────────────

export const getStats = () => api.get<Stats>("/stats/").then(r => r.data);

// ── Graph ─────────────────────────────────────────────────────────────────────

export const getGraph      = ()              => api.get("/graph/").then(r => r.data);
export const getNeighbors  = (id: number)    => api.get(`/graph/neighbors/${id}`).then(r => r.data);
export const rebuildGraph  = ()              => api.post("/graph/rebuild").then(r => r.data);

// ── Contradictions ────────────────────────────────────────────────────────────

export const getContradictions = () => api.get("/contradictions/").then(r => r.data);

// ── Watcher ───────────────────────────────────────────────────────────────────

export interface WatcherLocation {
  id:                 number;
  user_id:            number;
  path:               string;
  display_name:       string;
  location_type:      string;  // standard | custom | drive
  permission_status:  string;  // granted | pending | revoked | denied
  enabled:            boolean;
  created_at?:        string;
  updated_at?:        string;
  last_scan_at?:      string | null;
}

export const getWatcherStatus    = () => api.get("/watcher/status").then(r => r.data);
export const startWatcher        = () => api.post("/watcher/start").then(r => r.data);
export const stopWatcher         = () => api.post("/watcher/stop").then(r => r.data);
export const getWatcherLocations = () => api.get<WatcherLocation[]>("/watcher/locations").then(r => r.data);
export const addWatcherLocation  = (payload: { path: string; display_name: string; location_type?: string; permission_status?: string; enabled?: boolean }) =>
  api.post<WatcherLocation>("/watcher/locations", payload).then(r => r.data);
export const updateWatcherLocation = (id: number, payload: Partial<WatcherLocation>) =>
  api.patch<WatcherLocation>(`/watcher/locations/${id}`, payload).then(r => r.data);
export const deleteWatcherLocation = (id: number) =>
  api.delete(`/watcher/locations/${id}`).then(r => r.data);
export const pauseWatcherLocation  = (id: number) =>
  api.post<WatcherLocation>(`/watcher/locations/${id}/pause`).then(r => r.data);
export const resumeWatcherLocation = (id: number) =>
  api.post<WatcherLocation>(`/watcher/locations/${id}/resume`).then(r => r.data);

export interface LocationIndexStatus {
  location_id:  number;
  path:         string;
  running:      boolean;
  total:        number;
  processed:    number;
  skipped:      number;
  errors:       number;
  done:         boolean;
  current_file: string;
}

export const getLocationIndexStatus = (id: number) =>
  api.get<LocationIndexStatus>(`/watcher/locations/${id}/index-status`).then(r => r.data);

// ── Decay ─────────────────────────────────────────────────────────────────────

export const getDecayScore    = (id: number) => api.get(`/decay/score/${id}`).then(r => r.data);
export const reinforceMemory  = (id: number) => api.post(`/decay/reinforce/${id}`).then(r => r.data);

// ── Experiment / Ablation ─────────────────────────────────────────────────────

export const runExperiment = (config: ExperimentConfig) =>
  api.post<ExperimentResult>("/experiment/search", config).then(r => r.data);

// ── Desktop Sync ──────────────────────────────────────────────────────────────

export interface WatchedFolder {
  id: string;
  name: string;
  path: string;
  enabled: boolean;
  status?: string;
  file_count?: number;
}

export interface SyncDevice {
  id: number;
  device_id: string;
  device_name: string;
  os_info: string;
  status: string;
  pairing_code?: string | null;
  watched_folders: WatchedFolder[];
  last_heartbeat: string;
  last_sync: string | null;
  created_at: string;
  indexed_files_count?: number;
}

export interface SyncOverview {
  total_devices: number;
  total_indexed_files: number;
  devices: SyncDevice[];
}

export interface PairResponse {
  device_id: string;
  device_name: string;
  auth_token: string;
  status: string;
  pairing_code?: string;
  user_id?: number;
}

export const getSyncDevices = () =>
  api.get<SyncOverview>("/sync/devices").then(r => r.data);

export const pairDevice = (deviceName = "Windows PC", osInfo = "Windows") =>
  api.post<PairResponse>("/sync/pair", { device_name: deviceName, os_info: osInfo }).then(r => r.data);

export const generatePairingCode = (deviceName = "Windows PC", osInfo = "Windows") =>
  api.post<PairResponse>("/sync/pair", { device_name: deviceName, os_info: osInfo }).then(r => r.data);

export const unpairDevice = (deviceId: string) =>
  api.delete(`/sync/devices/${deviceId}`).then(r => r.data);

export const pauseDevice = (deviceId: string) =>
  api.post(`/sync/devices/${deviceId}/pause`).then(r => r.data);

export const resumeDevice = (deviceId: string) =>
  api.post(`/sync/devices/${deviceId}/resume`).then(r => r.data);

export const updateDeviceFolders = (deviceId: string, folders: WatchedFolder[]) =>
  api.post(`/sync/devices/${deviceId}/folders`, { watched_folders: folders }).then(r => r.data);

export const getSyncStatus = () =>
  api.get<SyncOverview>("/sync/status").then(r => r.data);
