-- Down migration for inbound checkpoint + callback quarantine (Wave C).
DROP TABLE IF EXISTS communication_inbound_quarantine;
DROP TABLE IF EXISTS communication_inbound_checkpoint;
