import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const [leadResult, messagesResult, stateResult, bookingResult] = await Promise.all([
    supabaseAdmin.from("leads").select("*").eq("id", id).maybeSingle(),
    supabaseAdmin
      .from("messages")
      .select("*")
      .eq("lead_id", id)
      .order("created_at", { ascending: true }),
    supabaseAdmin
      .from("conversation_state")
      .select("*")
      .eq("lead_id", id)
      .maybeSingle(),
    supabaseAdmin
      .from("bookings")
      .select("*")
      .eq("lead_id", id)
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
  ]);

  if (leadResult.error) {
    return NextResponse.json({ error: leadResult.error.message }, { status: 500 });
  }
  if (!leadResult.data) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  return NextResponse.json({
    lead: leadResult.data,
    messages: messagesResult.data ?? [],
    state: stateResult.data ?? null,
    booking: bookingResult.data ?? null,
  });
}
