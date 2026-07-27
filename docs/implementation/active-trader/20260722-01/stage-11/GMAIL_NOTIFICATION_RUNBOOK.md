# Gmail Notification Runbook — Stage 11
Operator notifications via `gog gmail send` to john@jwwhiting.com (proven every stage). Minimum
content: state, branch/PR, commits, Drive folder, tests, live-system impact, TODO, gates. NO
credential/secret value, NO raw market-data. For the unattended controller, §16K.10 requires a
proven send path — the gog lane is that path (OPERATOR_TODO A.4 confirms it). Unit tests mock the
send; each stage's real completion email confirms delivery (message ids recorded in closeouts).
