"use client";

import { useEffect, useRef, useState } from "react";
import type { Lead, Message, ConversationState } from "@/lib/types";
import { formatTime, initials, phaseColor, displayName } from "@/lib/format";
import ResetModal from "./ResetModal";

type Booking = {
  id: string;
  scheduled_at: string | null;
  status: string;
};

type Payload = {
  lead: Lead;
  messages: Message[];
  state: ConversationState | null;
  booking: Booking | null;
};

type Props = { leadId: string; onBack?: () => void };

export default function ChatView({ leadId, onBack }: Props) {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevCount = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    prevCount.current = 0;

    const fetchConv = async () => {
      try {
        const res = await fetch(`/api/leads/${leadId}`, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = (await res.json()) as Payload;
        if (!cancelled) {
          setData(json);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "failed");
      }
    };

    fetchConv();
    const interval = setInterval(fetchConv, 2500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [leadId]);

  useEffect(() => {
    if (!data) return;
    if (data.messages.length > prevCount.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
    prevCount.current = data.messages.length;
  }, [data]);

  if (error) {
    return <div className="flex h-full items-center justify-center text-sm text-red-400">Error: {error}</div>;
  }
  if (!data) {
    return <div className="flex h-full items-center justify-center text-sm text-zinc-500">Loading…</div>;
  }

  const { lead, messages, state, booking } = data;
  const name = displayName(lead.first_name, lead.last_name, lead.phone);
  const phase = state?.current_state ?? "Opening";

  return (
    <div className="flex h-full min-w-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-zinc-800 bg-zinc-950 px-5 py-3">
          <div className="flex items-center gap-3">
            {onBack && (
              <button
                onClick={onBack}
                className="mr-1 rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 md:hidden"
                aria-label="Back"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
              </button>
            )}
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-zinc-700 to-zinc-800 text-xs font-semibold">
              {initials(lead.first_name, lead.last_name)}
            </div>
            <div>
              <div className="text-sm font-medium">{name}</div>
              <div className="text-xs text-zinc-500">
                {lead.phone ?? "no phone"} {lead.company ? `· ${lead.company}` : ""}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setResetOpen(true)}
              className="rounded border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-[11px] font-medium text-zinc-300 hover:border-red-700 hover:bg-red-950 hover:text-red-300"
              title="Wipe state + re-fire opening template"
            >
              Reset
            </button>
            <div className={`flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium text-white ${phaseColor(phase)}`}>
              <span className="h-2 w-2 rounded-full bg-white/80" />
              {phase}
            </div>
          </div>
        </div>

        <ResetModal
          open={resetOpen}
          onClose={() => setResetOpen(false)}
          defaultPhone={lead.phone ?? ""}
          defaultFirstName={lead.first_name || "Test"}
          defaultCompany={lead.company || "your business"}
          defaultMessage={lead.form_message || ""}
        />

        <div
          className="scroll-thin flex-1 overflow-y-auto bg-[#0b141a] px-6 py-4"
          style={{
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='80' height='80' viewBox='0 0 80 80'><circle cx='40' cy='40' r='1' fill='%23ffffff' fill-opacity='0.02'/></svg>")`,
          }}
        >
          {messages.length === 0 && (
            <div className="flex h-full items-center justify-center">
              <div className="rounded-lg bg-zinc-900/60 px-4 py-3 text-center text-xs text-zinc-500">
                No messages yet. When {name || "the lead"} sends a WhatsApp message, it&apos;ll appear here.
              </div>
            </div>
          )}
          <div className="mx-auto flex max-w-2xl flex-col gap-1.5">
            {messages.map((m) => (
              <Bubble key={m.id} message={m} />
            ))}
            <div ref={bottomRef} />
          </div>
        </div>
      </div>

      <div className="hidden w-72 shrink-0 overflow-y-auto border-l border-zinc-800 bg-zinc-950 p-5 lg:block">
        <Section title="Lead">
          <Field label="Name" value={name} />
          <Field label="Phone" value={lead.phone ?? "—"} />
          <Field label="Email" value={lead.email ?? "—"} />
          <Field label="Company" value={lead.company ?? "—"} />
          <Field label="Industry" value={lead.industry ?? "—"} />
          <Field label="Source" value={lead.lead_source ?? "—"} />
        </Section>

        {lead.form_message && (
          <Section title="Form message">
            <div className="rounded-md bg-zinc-900 p-3 text-xs text-zinc-300">
              {lead.form_message}
            </div>
          </Section>
        )}

        <Section title="Status">
          <Field label="Phase" value={phase} />
          <Field label="Temperature" value={lead.temperature} />
          <Field label="Outcome" value={lead.outcome} />
          <Field label="Signal score" value={`${lead.signal_score}/10`} />
          <Field label="Messages" value={String(state?.message_count ?? messages.length)} />
        </Section>

        <Section title="Signals">
          <SignalRow label="Lead gen" score={state?.score_lead_gen ?? null} evidence={state?.signal_lead_gen ?? null} />
          <SignalRow label="Pain" score={state?.score_pain ?? null} evidence={state?.signal_pain ?? null} />
          <SignalRow label="Intent" score={state?.score_intent ?? null} evidence={state?.signal_intent ?? null} />
          <SignalRow label="Engagement" score={state?.score_engagement ?? null} evidence={state?.signal_engagement ?? null} />
          <Field label="Action" value={formatAction(state?.recommended_action)} />
        </Section>

        {state?.buying_signals && state.buying_signals.length > 0 && (
          <Section title="Buying signals">
            <ul className="space-y-1">
              {state.buying_signals.map((s, i) => (
                <li key={i} className="rounded-md bg-zinc-900 px-2.5 py-1.5 text-xs text-zinc-300">
                  {s}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {booking && (
          <Section title="Booking">
            <Field label="Scheduled" value={booking.scheduled_at ? new Date(booking.scheduled_at).toLocaleString() : "—"} />
            <Field label="Status" value={booking.status} />
          </Section>
        )}
      </div>
    </div>
  );
}

function Bubble({ message }: { message: Message }) {
  const outbound = message.direction === "outbound";
  return (
    <div className={`flex ${outbound ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[75%] rounded-lg px-3 py-1.5 text-sm leading-snug shadow-sm ${
          outbound ? "bg-[#005c4b] text-white" : "bg-[#202c33] text-zinc-100"
        }`}
      >
        <div className="whitespace-pre-wrap break-words">{message.content}</div>
        <div className="mt-0.5 text-right text-[10px] text-white/50">
          {formatTime(message.created_at)}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-5">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
        {title}
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-xs">
      <span className="text-zinc-500">{label}</span>
      <span className="truncate text-right text-zinc-200">{value}</span>
    </div>
  );
}

function formatAction(action: string | null | undefined): string {
  if (!action) return "—";
  return action
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function SignalRow({
  label,
  score,
  evidence,
}: {
  label: string;
  score: number | null;
  evidence: string | null;
}) {
  const scoreText = score === null || score === undefined ? "—" : `${score}/10`;
  const scoreColor =
    score === null
      ? "text-zinc-500"
      : score >= 8
      ? "text-emerald-400"
      : score >= 5
      ? "text-amber-400"
      : "text-zinc-400";
  return (
    <div className="space-y-0.5">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-zinc-500">{label}</span>
        <span className={`font-medium tabular-nums ${scoreColor}`}>{scoreText}</span>
      </div>
      {evidence && (
        <div className="text-[11px] leading-snug text-zinc-400">{evidence}</div>
      )}
    </div>
  );
}
