#!/bin/bash
# Keep last 7 audit runs
find /tmp -maxdepth 1 -name 'audit_*' -type d -mtime +7 -exec rm -rf {} \;
find /tmp -maxdepth 1 -name 'audit_*.tgz' -mtime +7 -delete
