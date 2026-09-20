"""Internal ops, intentionally outside Next's /api proxy. Token read from environment."""
import argparse
import json
import os
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["status", "clear-cache", "prune-telemetry", "refresh"])
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--username")
    parser.add_argument("--league")
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Use a loopback SSH tunnel; this CLI will not transmit the ops token remotely.")
    token = os.getenv("FANEDGE_OPS_TOKEN", "")
    if len(token) < 32:
        parser.error("Set FANEDGE_OPS_TOKEN to a secret of at least 32 characters.")
    path = f"/internal/ops/{args.operation}"
    if args.operation == "refresh":
        if not args.username or not args.league or not args.league.isdigit():
            parser.error("refresh requires --username and numeric --league")
        path = f"/api/leagues/{args.league}/refresh?{urlencode({'username': args.username})}"
    with urlopen(Request(args.url + path, data=b"", headers={"Authorization": f"Bearer {token}"}), timeout=90) as response:
        value = json.load(response)
    print(json.dumps(value if args.operation != "refresh" else value["meta"], indent=2))


if __name__ == "__main__":
    main()
