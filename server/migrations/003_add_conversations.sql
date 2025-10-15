-- Conversations table to log voice/chat interactions
CREATE TABLE IF NOT EXISTS conversations (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NULL,
  source VARCHAR(16) NOT NULL DEFAULT 'voice',
  transcript TEXT NOT NULL,
  reply TEXT NOT NULL,
  duration_ms INTEGER NULL,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Optional index for recent queries
CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON conversations (created_at DESC);
