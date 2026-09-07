#!/usr/bin/env python3
"""Manual end-to-end check of a running proxy.

Renamed out of the `test_*` namespace on purpose: it needs a live proxy and a
live upstream, so it does not belong in the pytest suite. It previously caught
every exception, printed it, and returned normally with no assertion anywhere
-- a broken proxy produced the same green run as a working one.

Now every check either passes or exits non-zero.

Usage:
    python scripts/verify_local_setup.py [target_url]

Environment:
    AIDLP_PROXY_URL          default http://localhost:8080
    AIDLP_PROXY_AUTH_TOKEN   sent as Proxy-Authorization when set
"""

import os
import sys

import requests

SECRET = "supersecretpassword123"
DEFAULT_TARGET = "http://httpbin.org/post"


def verify(proxy_url: str, target_url: str, token: str | None) -> None:
    proxies = {"http": proxy_url, "https": proxy_url}
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Proxy-Authorization"] = f"Bearer {token}"

    payload = {
        "messages": [
            {
                "role": "user",
                "content": f"My password is {SECRET} and my email is test@example.com.",
            }
        ],
        "stream": False,
    }

    print(f"Proxy   : {proxy_url}")
    print(f"Target  : {target_url}")

    response = requests.post(
        target_url, json=payload, proxies=proxies, headers=headers, timeout=15
    )

    print(f"Status  : {response.status_code}")
    if response.status_code != 200:
        raise AssertionError(
            f"expected 200 through the proxy, got {response.status_code}: "
            f"{response.text[:300]}"
        )

    body = response.text
    if SECRET in body:
        raise AssertionError(
            "the secret survived the proxy: it appears verbatim in the "
            "echoed body, so redaction did not run"
        )

    if "[REDACTED]" in body:
        print("Redaction: confirmed -- the secret was replaced in transit")
    else:
        # A target that does not echo the request (an LLM, for instance)
        # cannot prove redaction either way. Say so rather than imply a pass.
        print(
            "Redaction: NOT VERIFIED -- this target does not echo the request "
            "body. Point at an echo endpoint (the default) to check it."
        )


def main() -> int:
    proxy_url = os.environ.get("AIDLP_PROXY_URL", "http://localhost:8080")
    target_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET
    token = os.environ.get("AIDLP_PROXY_AUTH_TOKEN")

    try:
        verify(proxy_url, target_url, token)
    except AssertionError as e:
        print(f"FAIL: {e}")
        return 1
    except Exception as e:
        print(f"FAIL: could not reach the proxy or the target: {e}")
        print(
            "Check the proxy is running, and that a token is supplied via "
            "AIDLP_PROXY_AUTH_TOKEN if it binds a non-loopback interface."
        )
        return 2

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
