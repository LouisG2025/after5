"use client";

import { useState } from "react";
import ConversationList from "@/components/ConversationList";
import ChatView from "@/components/ChatView";

export default function Home() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="flex h-full">
      <aside className="w-80 shrink-0 bg-zinc-950">
        <ConversationList selectedId={selectedId} onSelect={setSelectedId} />
      </aside>
      <main className="flex min-w-0 flex-1 flex-col bg-zinc-900">
        {selectedId ? <ChatView leadId={selectedId} /> : <EmptyState />}
      </main>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
      <div className="text-5xl">💬</div>
      <div className="text-lg font-medium text-zinc-300">Albert Dashboard</div>
      <div className="max-w-sm text-sm text-zinc-500">
        Select a conversation on the left to see the full message history, conversation phase, and BANT scores.
      </div>
    </div>
  );
}
