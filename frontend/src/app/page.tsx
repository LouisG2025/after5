"use client";

import { useEffect, useState } from "react";
import ConversationList from "@/components/ConversationList";
import ChatView from "@/components/ChatView";
import ResetModal from "@/components/ResetModal";

export default function Home() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const initial = params.get("lead");
    if (initial) setSelectedId(initial);
    if (params.get("reset") === "1") setResetOpen(true);
  }, []);

  return (
    <div className="flex h-full">
      <aside className={`w-full shrink-0 bg-zinc-950 md:w-80 ${selectedId ? "hidden md:block" : ""}`}>
        <ConversationList selectedId={selectedId} onSelect={setSelectedId} />
      </aside>
      <main className={`flex min-w-0 flex-1 flex-col bg-zinc-900 ${selectedId ? "" : "hidden md:flex"}`}>
        {selectedId ? (
          <ChatView leadId={selectedId} onBack={() => setSelectedId(null)} />
        ) : (
          <EmptyState onStartTest={() => setResetOpen(true)} />
        )}
      </main>
      <ResetModal open={resetOpen} onClose={() => setResetOpen(false)} />
    </div>
  );
}

function EmptyState({ onStartTest }: { onStartTest: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
      <div className="text-5xl">💬</div>
      <div className="text-lg font-medium text-zinc-300">Albert Dashboard</div>
      <div className="max-w-sm text-sm text-zinc-500">
        Select a conversation on the left, or kick off a new test run to simulate a form submission.
      </div>
      <button
        onClick={onStartTest}
        className="mt-3 rounded-md border border-zinc-700 bg-zinc-900 px-4 py-2 text-xs font-medium text-zinc-200 hover:border-emerald-700 hover:bg-emerald-950 hover:text-emerald-300"
      >
        Start new test run
      </button>
    </div>
  );
}
