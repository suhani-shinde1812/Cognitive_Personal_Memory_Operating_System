// 📁 LOCATION: frontend/src/app/timeline/page.tsx
"use client";
import { useQuery } from "react-query";
import { motion } from "framer-motion";
import Link from "next/link";
import { getTimeline } from "@/services/api";
import { smartTitle, fileTypeIcon, fmtDate } from "@/utils/helpers";
import { Clock } from "lucide-react";

export default function TimelinePage() {
  const { data, isLoading } = useQuery(
    "timeline",
    () => getTimeline(500),
    { refetchInterval: 5000 }   // refresh every 5s while agent uploads
  );

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <Clock size={20} className="text-brand-400" /> Timeline
        </h1>
        <p className="text-sm text-gray-400 mt-0.5">
          All memories sorted by date
          {data?.total ? (
            <span className="ml-2 px-2 py-0.5 rounded-full bg-brand-600/20 text-brand-400 text-xs font-semibold">
              {data.total} total
            </span>
          ) : null}
        </p>
      </div>

      {isLoading && (
        <div className="flex justify-center py-20">
          <span className="animate-spin text-brand-400 text-2xl">⟳</span>
        </div>
      )}

      <div className="space-y-8">
        {(data?.groups || []).map((group: any, gi: number) => (
          <motion.div key={group.month} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: gi * 0.05 }}>
            {/* Month header */}
            <div className="flex items-center gap-3 mb-3">
              <div className="h-px flex-1 bg-surface-border" />
              <span className="text-xs font-semibold text-gray-400 px-3">{group.month}</span>
              <div className="h-px flex-1 bg-surface-border" />
            </div>

            {/* Memories in this month */}
            <div className="space-y-2 pl-4 border-l-2 border-surface-border ml-4">
              {group.memories.map((mem: any, i: number) => (
                <motion.div key={mem.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.03 }}>
                  <Link href={`/memory/${mem.id}`}>
                    <div className="card p-3 hover:border-brand-600/40 hover:bg-surface-hover transition-all cursor-pointer flex items-center gap-3 -ml-px">
                      <div className="w-2 h-2 rounded-full bg-brand-600 absolute -ml-5" />
                      <span className="text-lg">{fileTypeIcon(mem.file_type)}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white truncate">
                          {smartTitle(mem.source || "", mem.title)}
                        </p>
                        {mem.description && (
                          <p className="text-xs text-gray-500 truncate">{mem.description}</p>
                        )}
                      </div>
                      <span className="text-xs text-gray-600 shrink-0">{fmtDate(mem.date, "d MMM")}</span>
                    </div>
                  </Link>
                </motion.div>
              ))}
            </div>
          </motion.div>
        ))}
      </div>

      {!isLoading && !data?.groups?.length && (
        <div className="flex flex-col items-center py-20 gap-3">
          <Clock size={40} className="text-gray-700" />
          <p className="text-gray-400 text-sm">No memories yet. Upload some files to get started.</p>
        </div>
      )}
    </div>
  );
}