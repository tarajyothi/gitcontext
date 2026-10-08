#!/bin/sh
# Usage (compose):  docker compose -f docker-compose.prod.yml exec -T db pg_dump -U gitcontext gitcontext | gzip > backup-$(date +%F).sql.gz
# Restore:          gunzip -c backup-YYYY-MM-DD.sql.gz | docker compose -f docker-compose.prod.yml exec -T db psql -U gitcontext gitcontext
# This script is the same dump/restore against a reachable PostgreSQL (used to verify the procedure).
set -eu
case "${1:-}" in
  dump)    pg_dump "$2" | gzip > "$3" ;;
  restore) gunzip -c "$3" | psql -q "$2" ;;
  *) echo "usage: backup.sh dump|restore <postgres-url> <file.sql.gz>"; exit 2 ;;
esac
