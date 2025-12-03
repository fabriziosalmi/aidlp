import requests


def test_proxy():
    # Proxy URL (running in Docker)
    proxy_url = "http://localhost:8080"
    proxies = {
        "http": proxy_url,
        "https": proxy_url,
    }

    # Target URL (LM Studio running on Host)
    # We use host.docker.internal so the proxy (in Docker) can reach the host.
    # NOTE: This requires the client (this script) to be able to resolve host.docker.internal
    # OR we can just use a dummy URL if we just want to test DLP, but the user wants to test with LM Studio.
    # If we run this script from the HOST, we should probably use the actual IP or localhost if the proxy handles it?
    # Actually, if we send a request to "http://host.docker.internal:1234/v1/models",
    # the proxy will receive "GET http://host.docker.internal:1234/v1/models"
    # and try to resolve host.docker.internal, which we configured in docker-compose.
    target_url = "http://host.docker.internal:1234/v1/models"

    print(f"Testing DLP Proxy at {proxy_url} targeting {target_url}...")

    # 1. Test Connectivity & DLP (PII Redaction)
    # We'll simulate a chat completion request with PII
    payload = {
        "messages": [
            {
                "role": "user",
                "content": "My password is supersecretpassword123 and my email is test@example.com."
            }
        ],
        "temperature": 0.7,
        "max_tokens": -1,
        "stream": False
    }

    try:
        # We need to ensure the host machine can resolve host.docker.internal if we use it in the URL
        # usually it doesn't.
        # So we might need to trick it or use a different approach.
        # If we use "http://localhost:1234", the proxy inside docker will try to connect to ITS localhost.
        # So we MUST use a hostname that the proxy resolves to the host.
        # Let's try sending the request to http://host.docker.internal:1234
        # But requests library on host might fail to resolve it before sending to proxy?
        # No, if proxies are set, it should just forward the full URL to the proxy.

        response = requests.post(target_url, json=payload, proxies=proxies, timeout=10)

        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {response.headers}")
        print(f"Response Body: {response.text}")

        if response.status_code == 200:
            print("✅ Connection successful!")
        else:
            print("⚠️ Connection failed or returned error.")

    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nTip: Ensure LM Studio is running on port 1234 and 'host.docker.internal' is resolvable by the proxy.")


if __name__ == "__main__":
    test_proxy()
