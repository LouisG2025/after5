import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET() {
  const { data: leads, error: leadsError } = await supabaseAdmin
    .from("leads")
    .select("*")
    .order("created_at", { ascending: false });

  if (leadsError) {
    return NextResponse.json({ error: leadsError.message }, { status: 500 });
  }

  if (!leads || leads.length === 0) {
    return NextResponse.json({ leads: [] });
  }

  const leadIds = leads.map((l) => l.id);

  const [statesResult, lastMessagesResult] = await Promise.all([
    supabaseAdmin
      .from("conversation_state")
      .select("*")
      .in("lead_id", leadIds),
    supabaseAdmin
      .from("messages")
      .select("*")
      .in("lead_id", leadIds)
      .order("created_at", { ascending: false }),
  ]);

  const statesByLead = new Map<string, unknown>();
  for (const s of statesResult.data ?? []) statesByLead.set(s.lead_id, s);

  const lastMsgByLead = new Map<string, unknown>();
  for (const m of lastMessagesResult.data ?? []) {
    if (!lastMsgByLead.has(m.lead_id)) lastMsgByLead.set(m.lead_id, m);
  }

  const enriched = leads.map((l) => ({
    ...l,
    state: statesByLead.get(l.id) ?? null,
    last_message: lastMsgByLead.get(l.id) ?? null,
  }));

  enriched.sort((a, b) => {
    const aTime = (a.last_message as { created_at: string } | null)?.created_at ?? a.created_at;
    const bTime = (b.last_message as { created_at: string } | null)?.created_at ?? b.created_at;
    return bTime.localeCompare(aTime);
  });

  return NextResponse.json({ leads: enriched });
}
