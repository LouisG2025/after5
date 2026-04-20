export type Lead = {
  id: string;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  company: string | null;
  industry: string | null;
  lead_source: string | null;
  form_message: string | null;
  temperature: "Cold" | "Warm" | "Hot" | string;
  outcome: string;
  signal_score: number;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: string;
  lead_id: string;
  direction: "inbound" | "outbound";
  content: string;
  created_at: string;
};

export type ConversationState = {
  id: string;
  lead_id: string;
  current_state: string;
  bant_budget: string | null;
  bant_authority: string | null;
  bant_need: string | null;
  bant_timeline: string | null;
  message_count: number;
  last_active_at: string;
  updated_at: string;
};

export type LeadWithState = Lead & {
  state: ConversationState | null;
  last_message: Message | null;
};
