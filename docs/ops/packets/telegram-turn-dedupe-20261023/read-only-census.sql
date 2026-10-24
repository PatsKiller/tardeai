-- WP-29 operator-only aggregate measurement. No message text or provider IDs returned.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
WITH recent AS (
    SELECT role, channel, chat_id, message_id, subject_guid, text
    FROM operator_conversation_turns
    WHERE occurred_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
), duplicates AS (
    SELECT role, channel, chat_id, message_id, subject_guid, md5(text), count(*) AS copies
    FROM recent WHERE message_id IS NOT NULL
    GROUP BY 1,2,3,4,5,6 HAVING count(*) > 1
)
SELECT role, channel, count(*) AS duplicate_groups,
       sum(copies - 1) AS excess_identical_rows, max(copies) AS largest_group
FROM duplicates GROUP BY 1,2 ORDER BY 1,2;
COMMIT;
