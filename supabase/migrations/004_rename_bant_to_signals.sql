-- Replace BANT columns on conversation_state with Louis's new scoring categories:
--   bant_budget    -> signal_lead_gen
--   bant_need      -> signal_pain
--   bant_timeline  -> signal_intent
--   bant_authority -> signal_engagement
-- Also add buying_signals[] and recommended_action.

ALTER TABLE conversation_state RENAME COLUMN bant_budget    TO signal_lead_gen;
ALTER TABLE conversation_state RENAME COLUMN bant_need      TO signal_pain;
ALTER TABLE conversation_state RENAME COLUMN bant_timeline  TO signal_intent;
ALTER TABLE conversation_state RENAME COLUMN bant_authority TO signal_engagement;

ALTER TABLE conversation_state
  ADD COLUMN IF NOT EXISTS buying_signals     text[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS recommended_action text;
