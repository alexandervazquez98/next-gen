#!/bin/bash
# zero-co/docker/neo4j/entrypoint.sh

echo "DEBUG: Starting custom entrypoint script..."

# Find and delete ANY neo4j.pid file
echo "DEBUG: Searching for neo4j.pid files..."
find / -name "neo4j.pid" -type f -exec rm -f {} + -print

echo "DEBUG: Searching for .pid files in /data..."
find /data -name "*.pid" -type f -exec rm -f {} + -print

echo "DEBUG: Starting original entrypoint..."
exec /startup/docker-entrypoint.sh neo4j
