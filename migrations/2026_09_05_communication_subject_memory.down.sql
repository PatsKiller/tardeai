-- Down migration for Subject Memory / SubjectThread@v1.
DROP TABLE IF EXISTS communication_thread_membership;
DROP TABLE IF EXISTS communication_subjects;
