-- Seed fake conversations for dashboard UI development
-- Safe to run multiple times — clears fake leads first via phone number match

DELETE FROM leads WHERE phone IN ('+60123456001', '+60123456002', '+60123456003');

-- Lead 1: Marketing agency, in Discovery phase
WITH l1 AS (
  INSERT INTO leads (first_name, last_name, email, phone, company, industry, lead_source, form_message, temperature, outcome, signal_score)
  VALUES ('Aisha', 'Tan', 'aisha@brightmedia.my', '+60123456001', 'BrightMedia', 'Marketing Agency', 'Website Form',
          'Looking for a WhatsApp automation solution for our clients', 'Warm', 'In Progress', 6)
  RETURNING id
)
INSERT INTO messages (lead_id, direction, content, created_at)
SELECT id, d, c, now() - (i || ' minutes')::interval FROM l1,
  (VALUES
    (1, 'outbound', 'Hi Aisha — thanks for reaching out via the form. I''m Albert from After5. Got a sec to chat about what you''re looking for?'),
    (2, 'inbound', 'hey yeah sure'),
    (3, 'outbound', 'Awesome. So you mentioned WhatsApp automation — is this for BrightMedia itself or for your clients?'),
    (4, 'inbound', 'mostly clients. we run campaigns for a few e-commerce brands and the inbound volume is a lot'),
    (5, 'outbound', 'Makes sense. How many inbound messages are we talking per day roughly?'),
    (6, 'inbound', 'across all of them? probably 300-500'),
    (7, 'outbound', 'Got it. And right now — is someone replying manually or are you using any tool?'),
    (8, 'inbound', 'two VAs handling it but they miss stuff overnight')
  ) AS v(i, d, c);

INSERT INTO conversation_state (lead_id, current_state, signal_lead_gen, signal_pain, signal_intent, signal_engagement, buying_signals, recommended_action, message_count, last_active_at)
SELECT id, 'Discovery',
       '300-500 inbound/day across e-comm clients',
       'two VAs miss stuff overnight',
       NULL,
       'giving volume and staffing detail voluntarily',
       ARRAY['mentioned overnight coverage gap', 'volunteered inbound volume'],
       'continue_discovery',
       8, now() - interval '1 minutes'
FROM leads WHERE phone = '+60123456001';

-- Lead 2: Real estate, in Qualification, BANT scored
WITH l2 AS (
  INSERT INTO leads (first_name, last_name, email, phone, company, industry, lead_source, form_message, temperature, outcome, signal_score)
  VALUES ('Marcus', 'Lim', 'marcus@hauskey.com', '+60123456002', 'HausKey Realty', 'Real Estate', 'Website Form',
          'We waste too much time on unqualified leads — need a filter', 'Hot', 'In Progress', 9)
  RETURNING id
)
INSERT INTO messages (lead_id, direction, content, created_at)
SELECT id, d, c, now() - (i || ' minutes')::interval FROM l2,
  (VALUES
    (1, 'outbound', 'Hey Marcus — appreciate you filling out the form. Albert from After5 here. You mentioned lead qualification as the pain — want to unpack that a bit?'),
    (2, 'inbound', 'yeah. agents are spending 40% of their time on people who will never buy'),
    (3, 'outbound', 'Brutal. How are inbound leads hitting the team right now — WhatsApp? a form? both?'),
    (4, 'inbound', 'both. form on the site plus whatsapp from property portals'),
    (5, 'outbound', 'And what does "qualified" mean to you — is it budget, timeline, serious intent?'),
    (6, 'inbound', 'all three honestly. but mostly budget and timeline'),
    (7, 'outbound', 'Got it. Ballpark — how many leads a month, and how many agents do you have?'),
    (8, 'inbound', '~200 leads / 8 agents'),
    (9, 'outbound', 'Clear picture. Who makes the call on tools like this — you or someone else?'),
    (10, 'inbound', 'me. I''m the founder'),
    (11, 'outbound', 'Perfect. Timeline-wise — is this a now thing, next quarter, exploring?'),
    (12, 'inbound', 'now ideally. we''re losing deals')
  ) AS v(i, d, c);

INSERT INTO conversation_state (lead_id, current_state, signal_lead_gen, signal_pain, signal_intent, signal_engagement, buying_signals, recommended_action, message_count, last_active_at)
SELECT id, 'Qualification',
       '~200 leads/month from form + portals',
       'agents burning 40% of time on unqualified leads, losing deals',
       'wants this now, losing deals',
       'founder answering directly, detailed replies',
       ARRAY['losing deals now', 'founder is decision maker', 'willing to share numbers'],
       'push_for_booking',
       12, now() - interval '30 seconds'
FROM leads WHERE phone = '+60123456002';

-- Lead 3: Automotive, booked
WITH l3 AS (
  INSERT INTO leads (first_name, last_name, email, phone, company, industry, lead_source, form_message, temperature, outcome, signal_score)
  VALUES ('Priya', 'Raj', 'priya@autoflux.my', '+60123456003', 'AutoFlux', 'Automotive', 'Referral',
          'Referred by Louis — interested in discovery call', 'Hot', 'Meeting Booked', 10)
  RETURNING id
)
INSERT INTO messages (lead_id, direction, content, created_at)
SELECT id, d, c, now() - (i || ' hours')::interval FROM l3,
  (VALUES
    (1, 'outbound', 'Hi Priya! Louis said you''d be reaching out — Albert from After5 here. What''s on your mind?'),
    (2, 'inbound', 'hey. we need to automate the first few touches on test-drive leads. too slow currently'),
    (3, 'outbound', 'Yeah the first-touch speed is usually where deals die. How fast are you responding now?'),
    (4, 'inbound', 'anywhere from 20 min to 4 hours. terrible'),
    (5, 'outbound', 'Brutal. Ok — I think a 15-min call would be the fastest way to show you what''s possible. Louis free to jump in too if helpful. Here''s his link: https://calendly.com/after5/free-discovery-call'),
    (6, 'inbound', 'booked. thursday 3pm'),
    (7, 'outbound', 'Locked in. See you Thursday 👋')
  ) AS v(i, d, c);

INSERT INTO conversation_state (lead_id, current_state, signal_lead_gen, signal_pain, signal_intent, signal_engagement, buying_signals, recommended_action, message_count, last_active_at)
SELECT id, 'Confirmed',
       'inbound test-drive leads, current response 20min-4h',
       'first-touch speed killing deals',
       'booked discovery call immediately',
       'sharp replies, grabbed Calendly link fast',
       ARRAY['booked meeting', 'admitted current response is terrible', 'Louis referral'],
       'escalate_to_human',
       7, now() - interval '2 hours'
FROM leads WHERE phone = '+60123456003';

INSERT INTO bookings (lead_id, calendly_event_id, scheduled_at, status)
SELECT id, 'evt_fake_001', now() + interval '2 days', 'confirmed'
FROM leads WHERE phone = '+60123456003';
