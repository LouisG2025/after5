"use client";

import { useState } from "react";

type Props = {
  open: boolean;
  onClose: () => void;
  defaultPhone?: string;
  defaultFirstName?: string;
  defaultCompany?: string;
  defaultMessage?: string;
};

export default function ResetModal({
  open,
  onClose,
  defaultPhone = "",
  defaultFirstName = "Test",
  defaultCompany = "your business",
  defaultMessage = "",
}: Props) {
  const [phone, setPhone] = useState(defaultPhone);
  const [firstName, setFirstName] = useState(defaultFirstName);
  const [company, setCompany] = useState(defaultCompany);
  const [message, setMessage] = useState(defaultMessage);
  const [sendOutreach, setSendOutreach] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const apiKey = process.env.NEXT_PUBLIC_API_KEY || "";

  if (!open) return null;

  const handleReset = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${apiBase}/debug/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(apiKey && { "X-API-Key": apiKey }) },
        body: JSON.stringify({
          phone,
          first_name: firstName,
          company,
          message,
          send_outreach: sendOutreach,
        }),
      });
      const json = await res.json();
      if (!res.ok || json.error) {
        setError(json.error || `HTTP ${res.status}`);
      } else {
        setResult(
          `✓ Reset ${json.phone}. Redis keys deleted: ${json.redis_keys_deleted}. Outreach: ${json.outreach_scheduled ? "scheduled" : "skipped"}.`
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "network error");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg border border-zinc-800 bg-zinc-900 p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4">
          <h2 className="text-sm font-semibold">Reset conversation</h2>
          <p className="mt-1 text-xs text-zinc-500">
            Wipes the lead, messages, conversation state, and Redis session for this phone,
            then simulates a fresh form submission so Albert fires the opening template.
          </p>
        </div>

        <div className="space-y-3">
          <Field label="Phone" value={phone} onChange={setPhone} placeholder="+60123456789" />
          <Field label="First name" value={firstName} onChange={setFirstName} />
          <Field label="Company" value={company} onChange={setCompany} />
          <Field label="Form message (optional)" value={message} onChange={setMessage} textarea />
          <label className="flex items-center gap-2 text-xs text-zinc-300">
            <input
              type="checkbox"
              checked={sendOutreach}
              onChange={(e) => setSendOutreach(e.target.checked)}
              className="h-3.5 w-3.5 accent-emerald-500"
            />
            Send opening outreach after reset
          </label>
        </div>

        {error && (
          <div className="mt-3 rounded border border-red-900 bg-red-950/50 p-2 text-xs text-red-300">
            {error}
          </div>
        )}
        {result && (
          <div className="mt-3 rounded border border-emerald-900 bg-emerald-950/50 p-2 text-xs text-emerald-300">
            {result}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded px-3 py-1.5 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
          >
            Close
          </button>
          <button
            onClick={handleReset}
            disabled={running || !phone}
            className="rounded bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? "Resetting…" : "Reset & fire opening"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  textarea,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  textarea?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
        {label}
      </span>
      {textarea ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={2}
          className="w-full resize-none rounded border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full rounded border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
        />
      )}
    </label>
  );
}
