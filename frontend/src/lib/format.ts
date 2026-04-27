export function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function formatRelative(iso: string): string {
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString();
}

export function displayName(first: string, last: string, phone?: string | null): string {
  const full = `${first || ""} ${last || ""}`.trim();
  if (full) return full;
  if (phone) return formatPhone(phone);
  return "Unknown";
}

export function formatPhone(phone: string): string {
  return phone.replace("whatsapp:", "").replace(/^\+/, "+");
}

export function initials(first: string, last: string): string {
  const f = (first || "").trim();
  const l = (last || "").trim();
  if (!f && !l) return "#";
  return ((f[0] ?? "") + (l[0] ?? "")).toUpperCase() || "?";
}

export function phaseColor(state: string): string {
  const s = (state || "").toLowerCase();
  if (s.includes("opening")) return "bg-slate-500";
  if (s.includes("discovery")) return "bg-blue-500";
  if (s.includes("qualif")) return "bg-amber-500";
  if (s.includes("booking")) return "bg-violet-500";
  if (s.includes("confirm")) return "bg-emerald-500";
  if (s.includes("escalation")) return "bg-red-500";
  if (s.includes("waiting")) return "bg-zinc-500";
  if (s.includes("closed")) return "bg-zinc-700";
  return "bg-slate-500";
}

export function tempColor(temp: string): string {
  const t = (temp || "").toLowerCase();
  if (t === "hot") return "text-red-500";
  if (t === "warm") return "text-amber-500";
  if (t === "cold") return "text-blue-400";
  return "text-zinc-400";
}
