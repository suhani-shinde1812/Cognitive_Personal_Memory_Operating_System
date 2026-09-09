// 📁 LOCATION: frontend/src/components/Watcher/FolderPermissionsCard.tsx
"use client";
import React, { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  FolderCheck, HardDrive, Folder, CheckCircle2, XCircle, Pause, Play,
  Plus, UploadCloud, RefreshCw, Laptop, Copy, Check, Terminal, ShieldAlert,
  ShieldCheck, ArrowRight, Search, FileText, Image as ImageIcon, Sparkles
} from "lucide-react";
import toast from "react-hot-toast";
import { useRouter } from "next/navigation";
import {
  getWatcherLocations,
  pauseWatcherLocation,
  resumeWatcherLocation,
  addWatcherLocation,
  deleteWatcherLocation,
  generatePairingCode,
  getSyncDevices,
  getLocationIndexStatus,
  LocationIndexStatus,
  WatcherLocation,
  api,
  API_BASE_URL,
} from "@/services/api";

const ALLOWED_EXTENSIONS = new Set([
  ".pdf", ".docx", ".doc", ".txt", ".md", ".csv",
  ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"
]);

export default function FolderPermissionsCard({
  onMemoriesUpdated,
}: {
  onMemoriesUpdated?: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Locations Query
  const { data: locations = [], isLoading: loadingLocations } = useQuery(
    "watcher-locations",
    getWatcherLocations,
    { refetchInterval: 10000 }
  );

  // Sync Overview Query
  const { data: syncOverview } = useQuery("sync-devices", getSyncDevices, {
    refetchInterval: 5000,
  });

  const devices = syncOverview?.devices || [];
  const connectedDevice = devices.find((d) => d.status === "connected" || d.status === "watching");

  // Local state
  const [customPath, setCustomPath] = useState("");
  const [customName, setCustomName] = useState("");
  const [showAddModal, setShowAddModal] = useState(false);
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedCmd, setCopiedCmd] = useState(false);

  // Auto-indexing progress: keyed by location id
  const [indexingStatus, setIndexingStatus] = useState<Record<number, LocationIndexStatus>>({});
  const indexPollRefs = useRef<Record<number, NodeJS.Timeout>>({});

  // Syncing state
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState<{
    current: number;
    total: number;
    filename: string;
    folder: string;
  } | null>(null);
  const [targetSyncFolder, setTargetSyncFolder] = useState<string | null>(null);

  // Auto-index polling helper
  const startIndexPolling = (locationId: number) => {
    // Clear existing poll if any
    if (indexPollRefs.current[locationId]) {
      clearInterval(indexPollRefs.current[locationId]);
    }
    const poll = setInterval(async () => {
      try {
        const status = await getLocationIndexStatus(locationId);
        setIndexingStatus(prev => ({ ...prev, [locationId]: status }));
        if (status.done && !status.running) {
          clearInterval(poll);
          delete indexPollRefs.current[locationId];
          if (status.processed > 0 || status.skipped > 0) {
            queryClient.invalidateQueries("recent");
            queryClient.invalidateQueries("stats");
            if (onMemoriesUpdated) onMemoriesUpdated();
          }
        }
      } catch {
        // Silently ignore polling errors
      }
    }, 2000);
    indexPollRefs.current[locationId] = poll;
  };

  // Mutations
  const resumeMutation = useMutation(
    async (id: number) => await resumeWatcherLocation(id),
    {
      onSuccess: () => {
        queryClient.invalidateQueries("watcher-locations");
      },
      onError: () => {
        toast.error("Failed to enable folder");
      },
    }
  );

  // ── Allow + Auto-Sync (the real fix for cloud deployments) ───────────────
  // Since the backend runs on Render (cloud), its filesystem is empty.
  // We must upload files FROM the user's local PC via the browser.
  // Clicking "Agree & Allow" = enable in DB + immediately open folder picker.
  const handleAllowAndSync = async (loc: WatcherLocation) => {
    // 1. Enable in DB first
    try {
      await resumeWatcherLocation(loc.id);
      queryClient.invalidateQueries("watcher-locations");
    } catch {
      toast.error("Failed to enable folder");
      return;
    }

    toast.success(`✅ ${loc.display_name} allowed! Opening file picker to sync your documents…`, { duration: 4000 });

    // 2. Immediately open folder picker so files are uploaded from local PC
    await handleSyncFolderClick(loc.display_name);
  };

  const pauseMutation = useMutation(
    async (id: number) => await pauseWatcherLocation(id),
    {
      onSuccess: () => {
        queryClient.invalidateQueries("watcher-locations");
        toast.success("Folder access disallowed & paused.");
      },
      onError: () => {
        toast.error("Failed to pause folder");
      },
    }
  );

  const addLocationMutation = useMutation(
    async (payload: { path: string; display_name: string; location_type: string }) => {
      return await addWatcherLocation({
        path: payload.path,
        display_name: payload.display_name,
        location_type: payload.location_type,
        permission_status: "granted",
        enabled: true,
      });
    },
    {
      onSuccess: (data) => {
        queryClient.invalidateQueries("watcher-locations");
        toast.success(`Added & authorized: ${data.display_name}`);
        setShowAddModal(false);
        setCustomPath("");
        setCustomName("");
      },
      onError: (err: any) => {
        toast.error(err?.response?.data?.detail || "Failed to add location");
      },
    }
  );

  const pairMutation = useMutation(
    async () => await generatePairingCode("My Windows PC", "Windows 11"),
    {
      onSuccess: (data) => {
        if (data && data.pairing_code) {
          setPairingCode(data.pairing_code);
          toast.success("Pairing code generated!");
        } else {
          toast.error("Failed to generate pairing code. Please try again.");
        }
      },
      onError: (err: any) => {
        toast.error(err?.response?.data?.detail || "Failed to connect PC Watcher");
      },
    }
  );

  // ── Browser-based Direct Folder Syncing ───────────────────────────────────
  const handleSyncFolderClick = async (locName: string) => {
    setTargetSyncFolder(locName);

    // Try modern File System Access API
    if (typeof window !== "undefined" && "showDirectoryPicker" in window) {
      try {
        const dirHandle = await (window as any).showDirectoryPicker();
        await scanAndUploadDirectory(dirHandle, locName);
        return;
      } catch (err: any) {
        if (err.name === "AbortError") return; // User cancelled picker
        console.warn("DirectoryPicker failed, falling back to file input", err);
      }
    }

    // Fallback: trigger hidden webkitdirectory input
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleFileInputChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const folderName = targetSyncFolder || "Selected Folder";
    await uploadFileList(Array.from(files), folderName);
    e.target.value = ""; // Reset
  };

  const scanAndUploadDirectory = async (dirHandle: any, folderName: string) => {
    setIsSyncing(true);
    const filesToUpload: File[] = [];

    async function traverse(handle: any) {
      for await (const entry of handle.values()) {
        if (entry.kind === "file") {
          const file: File = await entry.getFile();
          const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
          if (ALLOWED_EXTENSIONS.has(ext)) {
            filesToUpload.push(file);
          }
        } else if (entry.kind === "directory") {
          // Skip system/hidden folders
          if (!entry.name.startsWith(".") && entry.name !== "node_modules" && entry.name !== "$RECYCLE.BIN") {
            try {
              await traverse(entry);
            } catch {
              // Ignore inaccessible subdirectories
            }
          }
        }
      }
    }

    toast.loading(`Scanning ${folderName}...`, { id: "scan-progress" });
    try {
      await traverse(dirHandle);
    } catch (err) {
      console.error("Traversal error:", err);
    }

    toast.dismiss("scan-progress");

    if (filesToUpload.length === 0) {
      toast.error(`No supported documents or images found in ${folderName}`);
      setIsSyncing(false);
      return;
    }

    await uploadFileList(filesToUpload, folderName);
  };

  const uploadFileList = async (files: File[], folderName: string) => {
    setIsSyncing(true);
    let successCount = 0;
    const total = files.length;

    // ── Concurrent batch upload (5 files at a time for speed) ─────────────
    const CONCURRENCY = 5;
    const chunks: File[][] = [];
    for (let i = 0; i < total; i += CONCURRENCY) {
      chunks.push(files.slice(i, i + CONCURRENCY));
    }

    let processed = 0;

    for (const chunk of chunks) {
      // Update progress with first file of chunk
      setSyncProgress({
        current: processed + 1,
        total,
        filename: chunk[0].name,
        folder: folderName,
      });

      // Upload chunk concurrently
      const results = await Promise.allSettled(
        chunk.map(async (file) => {
          const formData = new FormData();
          formData.append("file", file);
          await api.post("/upload/", formData, {
            headers: { "Content-Type": "multipart/form-data" },
          });
        })
      );

      for (const r of results) {
        if (r.status === "fulfilled") successCount++;
        processed++;
      }

      // Update progress after each chunk
      setSyncProgress(prev => prev ? { ...prev, current: processed } : null);
    }

    setIsSyncing(false);
    setSyncProgress(null);
    queryClient.invalidateQueries("recent");
    queryClient.invalidateQueries("stats");
    if (onMemoriesUpdated) onMemoriesUpdated();

    toast.success(
      `🧠 ${successCount} of ${total} files from ${folderName} converted into memories!`,
      { duration: 8000 }
    );
  };

  const copyText = (txt: string, type: "code" | "cmd") => {
    navigator.clipboard.writeText(txt);
    if (type === "code") {
      setCopiedCode(true);
      setTimeout(() => setCopiedCode(false), 2000);
    } else {
      setCopiedCmd(true);
      setTimeout(() => setCopiedCmd(false), 2000);
    }
    toast.success("Copied to clipboard!");
  };

  const getFolderIcon = (name: string, type: string) => {
    const n = name.toLowerCase();
    if (n.includes("drive") || type === "drive") return <HardDrive size={18} className="text-purple-400" />;
    if (n.includes("desktop")) return <Laptop size={18} className="text-blue-400" />;
    if (n.includes("document")) return <FileText size={18} className="text-emerald-400" />;
    if (n.includes("picture") || n.includes("photo")) return <ImageIcon size={18} className="text-amber-400" />;
    if (n.includes("download")) return <UploadCloud size={18} className="text-cyan-400" />;
    return <Folder size={18} className="text-indigo-400" />;
  };

  return (
    <div className="bg-[#121222]/90 border border-[#262640] rounded-2xl p-6 shadow-xl relative overflow-hidden backdrop-blur-md space-y-6">
      {/* Hidden File Input for fallback directory picker */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileInputChange}
        // @ts-ignore
        webkitdirectory="true"
        directory="true"
        multiple
        className="hidden"
      />

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#25253e] pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-brand-600/20 text-brand-400 flex items-center justify-center border border-brand-500/30">
              <FolderCheck size={20} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
                Folder & Drive Access Permissions
              </h2>
              <p className="text-xs text-gray-400">
                Choose which folders and drives you agree to allow CogniSphere to scan & convert into AI memories.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface hover:bg-surface-hover border border-surface-border text-xs font-semibold text-gray-200 transition-all cursor-pointer"
          >
            <Plus size={14} className="text-brand-400" />
            Add Custom Drive/Folder
          </button>

          <button
            onClick={() => pairMutation.mutate()}
            disabled={pairMutation.isLoading}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-xs font-semibold text-white transition-all shadow-md shadow-brand-600/20 cursor-pointer"
          >
            <Laptop size={14} />
            Connect PC Watcher
          </button>
        </div>
      </div>

      {/* ── Active Sync Progress Banner ─────────────────────────────────── */}
      <AnimatePresence>
        {isSyncing && syncProgress && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="bg-brand-950/40 border border-brand-500/40 rounded-xl p-4 space-y-2.5"
          >
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-brand-300 flex items-center gap-2">
                <RefreshCw size={14} className="animate-spin text-brand-400" />
                Converting {syncProgress.folder} files to memories...
              </span>
              <span className="font-mono text-gray-300 font-bold">
                {syncProgress.current} / {syncProgress.total} (
                {Math.round((syncProgress.current / syncProgress.total) * 100)}%)
              </span>
            </div>
            <div className="w-full h-2 bg-surface rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-brand-500 to-emerald-400 transition-all duration-200"
                style={{
                  width: `${(syncProgress.current / syncProgress.total) * 100}%`,
                }}
              />
            </div>
            <p className="text-[11px] text-gray-400 truncate">
              Current file: <span className="text-white font-mono">{syncProgress.filename}</span>
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Pairing Code Banner (if active) ─────────────────────────────── */}
      <AnimatePresence>
        {pairingCode && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            className="bg-gradient-to-r from-purple-950/40 to-brand-950/40 border border-brand-500/40 rounded-xl p-4 space-y-3"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Laptop size={16} className="text-brand-400" />
                <span className="text-xs font-bold text-white">
                  Continuous Windows Desktop Agent Pairing
                </span>
              </div>
              <button
                onClick={() => setPairingCode(null)}
                className="text-xs text-gray-400 hover:text-white"
              >
                Dismiss
              </button>
            </div>

            <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-[#0d0d1a] border border-[#2a2a44] p-3 rounded-xl">
              <div>
                <span className="text-[10px] uppercase font-bold text-gray-400">
                  Your 1-Time Pairing Code
                </span>
                <div className="text-xl font-mono font-extrabold text-brand-300 tracking-widest">
                  {pairingCode}
                </div>
              </div>
              <button
                onClick={() => copyText(pairingCode, "code")}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand-500/20 text-brand-300 hover:bg-brand-500/30 text-xs font-semibold"
              >
                {copiedCode ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                {copiedCode ? "Copied" : "Copy Code"}
              </button>
            </div>

            <div className="text-xs text-gray-300 font-mono bg-[#090912] p-2.5 rounded-lg flex items-center justify-between border border-[#1f1f33]">
              <span className="truncate mr-2">
                python desktop_agent\agent.py --code {pairingCode} --server {API_BASE_URL}
              </span>
              <button
                onClick={() =>
                  copyText(
                    `python desktop_agent\\agent.py --code ${pairingCode} --server ${API_BASE_URL}`,
                    "cmd"
                  )
                }
                className="text-brand-400 hover:text-brand-300 shrink-0"
              >
                {copiedCmd ? "Copied!" : "Copy Cmd"}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Folder / Drive Grid ─────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between text-xs text-gray-400 px-1">
          <span>Configured Locations ({locations.length})</span>
          <span className="text-[11px] text-gray-500">
            {locations.filter((l) => l.enabled).length} Allowed / {locations.length} Total
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {locations.map((loc: WatcherLocation) => {
            const isEnabled = loc.enabled;
            return (
              <div
                key={loc.id}
                className={`flex flex-col justify-between p-4 rounded-xl border transition-all ${
                  isEnabled
                    ? "bg-[#16162d]/90 border-emerald-500/30 shadow-sm"
                    : "bg-[#111120]/70 border-[#222238] opacity-80"
                }`}
              >
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="flex items-center gap-3">
                    <div
                      className={`w-9 h-9 rounded-lg flex items-center justify-center border ${
                        isEnabled
                          ? "bg-emerald-500/10 border-emerald-500/30"
                          : "bg-surface border-surface-border"
                      }`}
                    >
                      {getFolderIcon(loc.display_name, loc.location_type)}
                    </div>
                    <div>
                      <h4 className="text-sm font-bold text-white leading-tight">
                        {loc.display_name}
                      </h4>
                      <p className="text-[11px] font-mono text-gray-400 truncate max-w-[180px]">
                        {loc.path}
                      </p>
                    </div>
                  </div>

                  {/* Status Badge */}
                  {isEnabled ? (
                    <span className="flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                      <CheckCircle2 size={11} /> AGREED
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-gray-500/15 text-gray-400 border border-gray-500/30">
                      <XCircle size={11} /> DISALLOWED
                    </span>
                  )}
                </div>

                {/* Actions */}
                <div className="flex items-center justify-between pt-2 border-t border-[#232338]">
                  <button
                    onClick={() => {
                      if (isEnabled) {
                        pauseMutation.mutate(loc.id);
                      } else {
                        // Allow + immediately open file picker to upload from local PC
                        handleAllowAndSync(loc);
                      }
                    }}
                    disabled={pauseMutation.isLoading || resumeMutation.isLoading || isSyncing}
                    className={`text-xs font-semibold px-2.5 py-1.5 rounded-lg flex items-center gap-1.5 transition-all cursor-pointer ${
                      isEnabled
                        ? "bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30"
                        : "bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40"
                    }`}
                  >
                    {isEnabled ? (
                      <>
                        <Pause size={12} /> Disallow Access
                      </>
                    ) : (
                      <>
                        <Check size={12} /> Agree & Allow + Sync
                      </>
                    )}
                  </button>

                  <button
                    onClick={() => handleSyncFolderClick(loc.display_name)}
                    disabled={isSyncing}
                    className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1.5 rounded-lg bg-brand-600/20 hover:bg-brand-600/30 text-brand-300 border border-brand-500/30 transition-all cursor-pointer"
                  >
                    <UploadCloud size={12} />
                    Sync Files Now
                  </button>
                </div>

                {/* ── Browser Upload Progress (shown while syncing this folder) ── */}
                {isSyncing && syncProgress && syncProgress.folder === loc.display_name && (
                  <div className="mt-2 space-y-1.5">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-brand-300 font-semibold flex items-center gap-1.5">
                        <RefreshCw size={11} className="animate-spin" />
                        Uploading & converting…
                      </span>
                      <span className="font-mono text-gray-300">
                        {syncProgress.current}/{syncProgress.total}
                      </span>
                    </div>
                    <div className="w-full h-1.5 bg-[#1a1a2e] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-brand-500 to-emerald-400 transition-all duration-300"
                        style={{
                          width: syncProgress.total > 0
                            ? `${(syncProgress.current / syncProgress.total) * 100}%`
                            : "0%",
                        }}
                      />
                    </div>
                    <p className="text-[10px] text-gray-400 font-mono truncate">
                      {syncProgress.filename}
                    </p>
                  </div>
                )}

              </div>
            );
          })}
        </div>
      </div>

      {/* ── Quick Add Presets Bar ────────────────────────────────────────── */}
      <div className="pt-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-gray-400 font-medium">Quick add drives:</span>
        <button
          onClick={() =>
            addLocationMutation.mutate({
              path: "C:\\",
              display_name: "C: Drive",
              location_type: "drive",
            })
          }
          className="px-2.5 py-1 rounded-lg bg-surface border border-surface-border text-gray-300 hover:text-white hover:border-brand-500/40 cursor-pointer"
        >
          + C: Drive
        </button>
        <button
          onClick={() =>
            addLocationMutation.mutate({
              path: "E:\\",
              display_name: "E: Drive",
              location_type: "drive",
            })
          }
          className="px-2.5 py-1 rounded-lg bg-surface border border-surface-border text-gray-300 hover:text-white hover:border-brand-500/40 cursor-pointer"
        >
          + E: Drive
        </button>
        <button
          onClick={() =>
            addLocationMutation.mutate({
              path: "D:\\Projects",
              display_name: "D:\\Projects",
              location_type: "custom",
            })
          }
          className="px-2.5 py-1 rounded-lg bg-surface border border-surface-border text-gray-300 hover:text-white hover:border-brand-500/40 cursor-pointer"
        >
          + D:\Projects
        </button>
      </div>

      {/* ── Add Custom Location Modal ────────────────────────────────────── */}
      <AnimatePresence>
        {showAddModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.95 }}
              className="bg-[#18182e] border border-[#2f2f50] rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4"
            >
              <h3 className="text-base font-bold text-white">Add Authorized Folder or Drive</h3>
              <p className="text-xs text-gray-400">
                Enter the local Windows path to authorize for cognitive memory conversion.
              </p>

              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-300 mb-1">
                    Display Name
                  </label>
                  <input
                    type="text"
                    value={customName}
                    onChange={(e) => setCustomName(e.target.value)}
                    placeholder="e.g. Work Drive, E: Drive, Codebase"
                    className="w-full bg-[#0e0e1c] border border-[#2a2a45] rounded-xl px-3 py-2 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-brand-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-300 mb-1">
                    Folder or Drive Path
                  </label>
                  <input
                    type="text"
                    value={customPath}
                    onChange={(e) => setCustomPath(e.target.value)}
                    placeholder="e.g. E:\ or C:\Work\Projects"
                    className="w-full bg-[#0e0e1c] border border-[#2a2a45] rounded-xl px-3 py-2 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 font-mono"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3">
                <button
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-gray-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    if (!customPath.trim()) {
                      toast.error("Please provide a path");
                      return;
                    }
                    addLocationMutation.mutate({
                      path: customPath.trim(),
                      display_name: customName.trim() || customPath.trim(),
                      location_type: customPath.length <= 3 ? "drive" : "custom",
                    });
                  }}
                  disabled={addLocationMutation.isLoading}
                  className="px-4 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-xs font-semibold text-white cursor-pointer shadow"
                >
                  Authorize Folder
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
