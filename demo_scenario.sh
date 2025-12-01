#!/bin/bash

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== DLP Proxy Demo ===${NC}"
echo -e "${BLUE}1. Starting Proxy in background...${NC}"

# Start proxy in background and save PID
source venv/bin/activate
export PYTHONPATH=$PYTHONPATH:$(pwd)
python src/cli.py start --port 8081 > proxy.log 2>&1 &
PROXY_PID=$!

# Wait for proxy to start
sleep 3

echo -e "${BLUE}2. Sending Request with Sensitive Data...${NC}"
echo -e "${BLUE}Scenario: Developer asking ChatGPT to optimize a query with prod credentials${NC}"
DEMO_TEXT="Hi ChatGPT, can you help me optimize this query? I am connecting to postgres://admin:secret_password_123@db-prod.internal:5432/users and it is very slow. My API key is sk-live-secret_key_999."
echo -e "${GREEN}Request Body: '$DEMO_TEXT'${NC}"

# Send request through proxy
# We use httpbin.org/post to echo back the data received by the server
curl -x http://localhost:8081 -X POST http://httpbin.org/post \
     -d "$DEMO_TEXT" \
     -s | grep -A 5 "form"

echo -e "\n${BLUE}3. Waiting for stats flush...${NC}"
sleep 2
echo -e "${BLUE}4. Checking Proxy Stats...${NC}"
export PYTHONPATH=$PYTHONPATH:$(pwd)
python src/cli.py stats

echo -e "${BLUE}5. Stopping Proxy...${NC}"
kill $PROXY_PID 2>/dev/null || true
wait $PROXY_PID 2>/dev/null

echo -e "${BLUE}=== Demo Complete ===${NC}"
