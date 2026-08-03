#!/usr/bin/env python3
"""
本地运行：用 Slack 邮箱密码登录，打印 token 和 cookie。
然后通过生产环境 API 写入。

用法:
    # 从 .env 读取账号密码
    python scripts/slack_login_cli.py

    # 指定账号密码
    python scripts/slack_login_cli.py --email xxx@gmail.com --password xxxx

    # 登录成功后直接写入生产环境
    python scripts/slack_login_cli.py --deploy http://123.57.0.174:9527
"""
import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("slack_login")


def load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def login(email: str, password: str, ws: str = "vllm-dev"):
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    })

    logger.info(f"Logging in to {ws}.slack.com as {email}...")

    r = s.get(f"https://{ws}.slack.com/sign_in_with_password", timeout=15)
    m = re.search(r'crumbValue&quot;:&quot;(.*?)&quot;', r.text)
    if not m:
        logger.error("Failed to extract crumb")
        sys.exit(1)

    crumb = m.group(1).encode().decode("unicode_escape")

    login_resp = s.post(f"https://{ws}.slack.com/sign_in_with_password", data={
        "signin": "1", "redir": "", "has_remember": "true",
        "crumb": crumb, "remember": "remember",
        "email": email, "password": password,
    }, allow_redirects=True, timeout=15)

    d_cookie = s.cookies.get("d")
    if not d_cookie:
        logger.error(f"Login failed (status={login_resp.status_code}, url={login_resp.url})")
        logger.error("No d cookie received. Slack may be blocking this IP or requiring CAPTCHA.")
        sys.exit(1)

    r2 = s.get(f"https://{ws}.slack.com/", timeout=15)
    m2 = re.search(r'xoxc-[a-zA-Z0-9-]+', r2.text)
    if not m2:
        logger.error("No xoxc token found after login")
        sys.exit(1)

    token = m2.group(0)
    cookie = d_cookie

    logger.info(f"✓ Login successful!")
    logger.info(f"  Token:  {token[:40]}...")
    logger.info(f"  Cookie: {cookie[:40]}...")
    return token, cookie


def deploy_to_production(api_url: str, token: str, cookie: str):
    """写入生产环境"""
    resp = requests.put(
        f"{api_url}/api/slack/config",
        json={"token": token, "cookie": cookie},
        timeout=15,
    )
    if resp.ok:
        logger.info(f"✓ Deployed to {api_url}")
    else:
        logger.error(f"✗ Deploy failed: {resp.status_code} {resp.text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Slack login helper")
    parser.add_argument("--email", help="Slack email")
    parser.add_argument("--password", help="Slack password")
    parser.add_argument("--deploy", metavar="URL", help="Production API base URL to deploy credentials to")
    parser.add_argument("--ws", default="vllm-dev", help="Slack workspace (default: vllm-dev)")
    args = parser.parse_args()

    load_env()
    email = args.email or os.getenv("SLACK_EMAIL")
    password = args.password or os.getenv("SLACK_PASSWORD")

    if not email or not password:
        logger.error("Email and password required. Set SLACK_EMAIL/SLACK_PASSWORD in .env or pass via --email/--password")
        sys.exit(1)

    token, cookie = login(email, password, args.ws)

    print(f"\n--- Copy these to Slack config page ---")
    print(f"Token:  {token}")
    print(f"Cookie: {cookie}")
    print(f"----------------------------------------\n")

    if args.deploy:
        deploy_to_production(args.deploy, token, cookie)