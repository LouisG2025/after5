-- Enable Row Level Security on all tables
-- Note: Service role key bypasses RLS, so this won't affect the backend app
-- This protects against accidental exposure via anon key
--
-- No policies are created because:
-- 1. The app uses the service role key (bypasses RLS)
-- 2. Creating "USING (true)" policies triggers linter warnings
-- 3. With RLS enabled and no policies, anon key has zero access (secure)

ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_data ENABLE ROW LEVEL SECURITY;
