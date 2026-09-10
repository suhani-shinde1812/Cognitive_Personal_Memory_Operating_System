// 📁 LOCATION: frontend/src/app/page.tsx
"use client";
import { useQuery, useQueryClient } from "react-query";
import { motion } from "framer-motion";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStats, getRecent, checkHealth, API_BASE_URL } from "@/services/api";
import { smartTitle, relativeDate, fileTypeIcon } from "@/utils/helpers";
import SearchBar from "@/components/Search/SearchBar";
import FolderPermissionsCard from "@/components/Watcher/FolderPermissionsCard";
import {
  Layers, Target, FileStack, Activity, ChevronRight,
  TrendingUp, Wifi, WifiOff, MessageSquare, Upload,
} from "lucide-react";

export default function Dashboard() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: stats  } = useQuery("stats",  getStats,         { refetchInterval: 5000 });
  const { data: recent } = useQuery("recent", () => getRecent(8), { refetchInterval: 5000 });
  const { data: health, isSuccess } = useQuery("health", async () => {
    console.log("[CogniSphere] API URL:", API_BASE_URL);
    console.log("[CogniSphere] Health URL:", `${API_BASE_URL}/health`);
    try {
      const res = await checkHealth();
      console.log("[CogniSphere] Health response:", res);
      return res;
    } catch (err) {
      console.error("[CogniSphere] Health check failed:", err);
      throw err;
    }
  }, { retry: 1, refetchInterval: 15000 });

  const handleSearch = (q: string, mode: string) => {
    router.push(`/search?q=${encodeURIComponent(q)}&mode=${mode}`);
  };

  const statCards = [
    { label:"Memories",      value:stats?.totals?.memories       ?? "–", icon:FileStack,  color:"text-blue-400"   },
    { label:"Active Goals",  value:stats?.goals?.active          ?? "–", icon:Target,     color:"text-yellow-400" },
    { label:"Retrievals",    value:stats?.acma?.total_retrievals ?? "–", icon:Activity,   color:"text-green-400"  },
    { label:"Avg Quality",   value:stats ? `${((stats.acma?.avg_importance_score || 0)*100).toFixed(0)}%` : "–", icon:TrendingUp, color:"text-purple-400" },
  ];

  const isConnected = !!health || isSuccess;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">

      {/* Hero */}
      <motion.div initial={{ opacity:0, y:16 }} animate={{ opacity:1, y:0 }}>
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl bg-brand-600 flex items-center justify-center">
              <Layers size={22} className="text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Cognisphere</h1>
              <p className="text-sm text-gray-400">Personal Cognitive Memory OS</p>
            </div>
          </div>
          <div className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border ${
            isConnected
              ? "bg-green-900/20 border-green-700/30 text-green-400"
              : "bg-red-900/20 border-red-700/30 text-red-400"
          }`}>
            {isConnected ? <Wifi size={11} /> : <WifiOff size={11} />}
            {isConnected ? "Connected" : "Backend offline"}
          </div>
        </div>

        {/* Search */}
        <SearchBar onSearch={handleSearch} large autoFocus />
      </motion.div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {statCards.map((s, i) => (
          <motion.div key={s.label} initial={{ opacity:0, y:10 }} animate={{ opacity:1, y:0 }}
            transition={{ delay: i * 0.05 }} className="card p-4">
            <s.icon size={16} className={s.color + " mb-2"} />
            <div className="text-2xl font-bold text-white">{s.value}</div>
            <div className="text-xs text-gray-500 mt-0.5">{s.label}</div>
          </motion.div>
        ))}
      </div>

      {/* ── Prominent Folder & Drive Permissions + Instant Sync Section ── */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
        <FolderPermissionsCard
          onMemoriesUpdated={() => {
            queryClient.invalidateQueries("recent");
            queryClient.invalidateQueries("stats");
          }}
        />
      </motion.div>

      {/* Quick actions */}
      <div className="grid grid-cols-2 gap-3">
        <Link href="/upload">
          <motion.div initial={{ opacity:0 }} animate={{ opacity:1 }} transition={{ delay:0.2 }}
            className="card p-4 hover:border-brand-600/50 hover:bg-surface-hover transition-all cursor-pointer flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-brand-600/20 flex items-center justify-center">
              <Upload size={16} className="text-brand-400" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">Upload Files</p>
              <p className="text-xs text-gray-500">Add documents to your memory</p>
            </div>
          </motion.div>
        </Link>
        <Link href="/chat">
          <motion.div initial={{ opacity:0 }} animate={{ opacity:1 }} transition={{ delay:0.25 }}
            className="card p-4 hover:border-brand-600/50 hover:bg-surface-hover transition-all cursor-pointer flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-brand-600/20 flex items-center justify-center">
              <MessageSquare size={16} className="text-brand-400" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">Ask AI</p>
              <p className="text-xs text-gray-500">Chat about your documents</p>
            </div>
          </motion.div>
        </Link>
      </div>

      {/* File type breakdown */}
      {stats?.files?.by_type && Object.keys(stats.files.by_type).length > 0 && (
        <motion.div initial={{ opacity:0 }} animate={{ opacity:1 }} transition={{ delay:0.3 }} className="card p-5 mb-5">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Document Types</h2>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.files.by_type).map(([type, count]) => (
              <Link key={type} href={`/search?q=&mode=keyword&file_type=${type}`}>
                <div className="flex items-center gap-2 bg-surface-hover hover:bg-surface-border px-3 py-1.5 rounded-lg cursor-pointer transition-colors">
                  <span className="text-base">{fileTypeIcon(type)}</span>
                  <span className="text-sm font-semibold text-white">{count as number}</span>
                  <span className="text-xs text-gray-500 uppercase">{type}</span>
                </div>
              </Link>
            ))}
          </div>
        </motion.div>
      )}

      {/* Recent memories */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Recently Added</h2>
        <Link href="/timeline" className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
          View all <ChevronRight size={12} />
        </Link>
      </div>

      <div className="space-y-2">
        {(!recent || recent.length === 0) && (
          <div className="card p-6 text-center">
            <p className="text-gray-400 text-sm">No documents yet</p>
            <Link href="/upload" className="text-brand-400 text-xs mt-2 block">Upload your first file →</Link>
          </div>
        )}
        {(recent || []).map((mem: any, i: number) => (
          <motion.div key={mem.id} initial={{ opacity:0, x:-8 }} animate={{ opacity:1, x:0 }}
            transition={{ delay: i * 0.04 }}>
            <Link href={`/memory/${mem.id}`}>
              <div className="card p-3 hover:border-brand-600/40 hover:bg-surface-hover transition-all flex items-center gap-3">
                <span className="text-lg shrink-0">{fileTypeIcon(mem.file_type)}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-white truncate">
                    {smartTitle(mem.source || "", mem.title)}
                  </p>
                  <p className="text-xs text-gray-500">{relativeDate(mem.date)}</p>
                </div>
                <ChevronRight size={13} className="text-gray-600 shrink-0" />
              </div>
            </Link>
          </motion.div>
        ))}
      </div>
    </div>
  );
}