#!/bin/bash
cd "$(dirname "$0")"

# Start MCP server in background
.venv/bin/python -m src.server &
SERVER_PID=$!
echo "MCP server started (PID $SERVER_PID)"

# Wait for it to be ready
echo "Waiting for server..."
for i in {1..10}; do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/mcp --max-time 1 | grep -q "406\|200"; then
        echo "Server ready."
        break
    fi
    sleep 0.5
done

# Open Claude Code
claude
