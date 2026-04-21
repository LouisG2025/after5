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
  signal_lead_gen: string | null;
  signal_pain: string | null;
  signal_intent: string | null;
  signal_engagement: string | null;
  score_lead_gen: number | null;
  score_pain: number | null;
  score_intent: number | null;
  score_engagement: number | null;
  buying_signals: string[] | null;
  recommended_action: string | null;
  message_count: number;
  last_active_at: string;
  updated_at: string;
};

export type LeadWithState = Lead & {
  state: ConversationState | null;
  last_message: Message | null;
};
