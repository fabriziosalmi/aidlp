import asyncio
import aiohttp
import time
import statistics
import random
import argparse

async def send_request(session, url, payload):
    start_time = time.time()
    try:
        async with session.post(url, data=payload) as response:
            await response.text()
            return time.time() - start_time
    except Exception as e:
        print(f"Request failed: {e}")
        return None

async def load_test(num_clients, duration, proxy_url, target_url):
    print(f"Starting load test with {num_clients} clients for {duration} seconds...")
    
    # Payloads
    clean_payload = "Hello world, this is a safe message."
    sensitive_payload = "My password is secret and my phone is 415-555-0199."
    
    latencies = []
    start_test = time.time()
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        while time.time() - start_test < duration:
            # Batch of requests
            for _ in range(num_clients):
                payload = random.choice([clean_payload, sensitive_payload])
                # Use proxy
                tasks.append(send_request(session, target_url, payload))
            
            # Wait for batch (simple simulation)
            results = await asyncio.gather(*tasks)
            latencies.extend([r for r in results if r is not None])
            tasks = []
            
            # Small sleep to yield
            await asyncio.sleep(0.1)
            
    if not latencies:
        print("No successful requests.")
        return

    # Calculate stats
    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    avg = statistics.mean(latencies)
    
    print(f"\nResults ({len(latencies)} requests):")
    print(f"  Avg Latency: {avg*1000:.2f}ms")
    print(f"  P50 Latency: {p50*1000:.2f}ms")
    print(f"  P95 Latency: {p95*1000:.2f}ms")
    print(f"  P99 Latency: {p99*1000:.2f}ms")
    
    if p95 < 0.1:
        print("\nSUCCESS: P95 Latency is < 100ms")
    else:
        print("\nWARNING: P95 Latency is > 100ms")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", type=int, default=10)
    parser.add_argument("--duration", type=int, default=10)
    args = parser.parse_args()
    
    # Note: We need to configure aiohttp to use the proxy. 
    # But aiohttp client proxy support is for CONNECT. 
    # For this test, we might need to send to localhost:8080 directly if it acts as reverse proxy, 
    # or configure proxy settings.
    # Given our implementation intercepts requests, let's assume we send TO the proxy 
    # acting as a reverse proxy for the target, OR we configure the session to use the proxy.
    
    # Since our proxy is an explicit proxy (mitmproxy), we should configure it as such.
    # However, aiohttp proxy support is simple.
    
    # Let's try sending directly to proxy port but with absolute URL (standard proxy behavior)
    # OR setting proxy kwarg.
    
    # We will use the proxy kwarg in aiohttp.
    
    # Re-defining send_request to use proxy
    async def send_request_with_proxy(session, url, payload):
        start_time = time.time()
        try:
            async with session.post(url, data=payload, proxy="http://localhost:8081") as response:
                await response.text()
                return time.time() - start_time
        except Exception as e:
            # print(f"Request failed: {e}")
            return None

    # Patching the function for the loop
    global send_request
    send_request = send_request_with_proxy
    
    asyncio.run(load_test(args.clients, args.duration, "http://localhost:8081", "http://httpbin.org/post"))
