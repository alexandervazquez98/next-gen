#!/bin/bash
# monitor_performance.sh - Monitoreo de I/O para NEX-GEN Collector

echo "NEX-GEN Performance Monitor - Press Ctrl+C to stop"
echo "--------------------------------------------------"

while true; do
    echo "Time: $(date +%H:%M:%S)"
    
    # Docker Stats (CPU/MEM)
    echo "Resource Usage:"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}" nexgen_snmp_engine nexgen_postgres nexgen_neo4j
    
    # Database Specifics (Simple count growth)
    echo "Data Growth (Postgres Metrics):"
    docker exec nexgen_postgres psql -U nexgen_admin -d nexgen_auth -c "SELECT count(*) as total_metric_values FROM metric_values;" | grep -A 1 "total" | tail -n 1
    
    echo "--------------------------------------------------"
    sleep 10
done
