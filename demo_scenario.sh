#!/bin/bash

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== DLP Proxy Demo ===${NC}"
echo -e "${BLUE}1. Starting Proxy in background...${NC}"

# Start proxy in background and save PID
source venv/bin/activate
python src/cli.py start --port 8081 > proxy.log 2>&1 &
PROXY_PID=$!

# Wait for proxy to start
sleep 3

echo -e "${BLUE}2. Sending Request with Sensitive Data...${NC}"
echo -e "${GREEN}Request Body: 'My password is secret and call me at 415-555-0199'${NC}"

# Send request through proxy
# We use httpbin.org/post to echo back the data received by the server
curl -x http://localhost:8081 -X POST http://httpbin.org/post \
     -d "My password is secret and call me at 415-555-0199" \
     -s | grep -A 5 "form"

echo -e "\n${BLUE}3. Waiting for stats flush...${NC}"
sleep 2
echo -e "${BLUE}4. Checking Proxy Stats...${NC}"
python src/cli.py stats

echo -e "${BLUE}5. Stopping Proxy...${NC}"
kill $PROXY_PID
wait $PROXY_PID 2>/dev/null

echo -e "${BLUE}=== Demo Complete ===${NC}"
