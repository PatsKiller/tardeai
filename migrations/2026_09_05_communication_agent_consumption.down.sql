-- Down migration for AgentConsumptionReceipt@v1 + subscriptions.
DROP TABLE IF EXISTS communication_agent_consumption_receipts;
DROP TABLE IF EXISTS communication_agent_subscriptions;
