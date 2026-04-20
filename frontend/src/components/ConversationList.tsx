"use client";

import { useEffect, useState } from "react";
import type { LeadWithState } from "@/lib/types";
import { formatRelative, initials, phaseColor, tempColor } from "@/lib/format";

type Props = {
  selectedId: string | null;
  onSelect: (id: string) => void;
};

export default function ConversationList({ selectedId, onSelect }: Props) {
  const [leads, setLeads] = useState<LeadWithState[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchLeads = async () => {
      try {
        const res = await fetch("/api/leads", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!cancelled) {
          setLeads(json.leads ?? []);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchLeads();
    const interval = setInterval(fetchLeads, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="flex h-full flex-col border-r border-zinc-800">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div>
          <h1 className="text-sm font-semibold">Conversations</h1>
          <p className="text-xs text-zinc-500">
            {leads.length} {leads.length === 1 ? "lead" : "leads"}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
          <span className="text-[10px] uppercase tracking-wide text-zinc-500">Live</span>
        </div>
      </div>

      <div className="scroll-thin flex-1 overflow-y-auto">
        {loading && leads.length === 0 && (
          <div className="p-4 text-sm text-zinc-500">Loading…</div>
        )}
        {error && (
          <div className="p-4 text-sm text-red-400">Error: {error}</div>
        )}
        {!loading && !error && leads.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
            <div className="text-3xl">💬</div>
            <div className="text-sm text-zinc-400">No conversations yet</div>
            <div className="text-xs text-zinc-600">
              Submit a form or message the bot on WhatsApp to see a lead here.
            </div>
          </div>
        )}
        {leads.map((lead) => {
          const selected = selectedId === lead.id;
          const name = `${lead.first_name || ""} ${lead.last_name || ""}`.trim() || "Unknown";
          const preview = lead.last_message?.content ?? lead.form_message ?? "(no messages yet)";
          const time = lead.last_message?.created_at ?? lead.created_at;
          const phase = lead.state?.current_state ?? "Opening";

          return (
            <button
              key={lead.id}
              onClick={() => onSelect(lead.id)}
              className={`flex w-full items-start gap-3 border-b border-zinc-900 px-4 py-3 text-left transition hover:bg-zinc-900 ${
                selected ? "bg-zinc-900" : ""
              }`}
            >
              <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-zinc-700 to-zinc-800 text-xs font-semibold text-zinc-200">
                {initials(lead.first_name, lead.last_name)}
                <span
                  className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-zinc-950 ${phaseColor(phase)}`}
                  title={phase}
                />
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-sm font-medium text-zinc-100">{name}</span>
                  <span className="shrink-0 text-[10px] text-zinc-500">
                    {formatRelative(time)}
                  </span>
                </div>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-xs text-zinc-400">{preview}</span>
                </div>
                <div className="mt-1 flex items-center gap-2 text-[10px]">
                  <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-zinc-300">
                    {phase}
                  </span>
                  {lead.company && (
                    <span className="truncate text-zinc-500">{lead.company}</span>
                  )}
                  <span className={`ml-auto font-medium ${tempColor(lead.temperature)}`}>
                    {lead.temperature}
                  </span>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
