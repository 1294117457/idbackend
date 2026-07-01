"""邮箱验证码：限流 + 发送 + 验证"""
import ssl
import asyncio
import random
import smtplib
import string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Tuple

from .redis import RedisCache, get_redis
from .config import get_settings

settings = get_settings()

_CODE_PREFIX = "email_code"
_RL_1M_PREFIX = "rl:email_code:1m"
_RL_1H_PREFIX = "rl:email_code:1h"


def _smtp_send_code(to_email: str, code: str, expire_minutes: int = 5):
    message = MIMEMultipart("alternative")
    message["From"] = settings.SMTP_FROM or settings.SMTP_USERNAME
    message["To"] = to_email
    message["Subject"] = "您的验证码"
    message.attach(MIMEText(
        f"<html><body>"
        f"<p>您的验证码是: <strong style='font-size:24px'>{code}</strong></p>"
        f"<p>有效期 {expire_minutes} 分钟，请勿泄露给他人。</p>"
        f"</body></html>",
        "html",
    ))

    if settings.SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT,
            context=ssl.create_default_context(), timeout=60,
        )
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=60)
        server.ehlo()
        server.starttls()
        server.ehlo()

    try:
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(message)
    finally:
        server.quit()


def _make_code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


class EmailCode:
    """邮箱验证码工具，返回 (ok: bool, msg: str)"""

    @staticmethod
    async def send(
        email: str,
        code_type: str,
        expire_minutes: int = 5,
    ) -> Tuple[bool, str]:
        redis = await get_redis()
        cache = RedisCache(redis)

        allowed, _ = await cache.rate_limit(
            f"{_RL_1M_PREFIX}:{code_type}:{email}", max_count=1, window_seconds=60
        )
        if not allowed:
            return False, "发送过于频繁，请 1 分钟后再试"

        allowed, _ = await cache.rate_limit(
            f"{_RL_1H_PREFIX}:{code_type}:{email}", max_count=5, window_seconds=3600
        )
        if not allowed:
            return False, "发送次数已达上限，请 1 小时后再试"

        code = _make_code()
        code_key = f"{_CODE_PREFIX}:{code_type}:{email}"
        await cache.set(code_key, code, expire=expire_minutes * 60)

        try:
            await asyncio.to_thread(_smtp_send_code, email, code, expire_minutes)
        except Exception as e:
            await cache.delete(code_key)
            return False, f"邮件发送失败: {e}"

        return True, code

    @staticmethod
    async def verify(
        email: str,
        code_type: str,
        input_code: str,
    ) -> Tuple[bool, str]:
        redis = await get_redis()
        cache = RedisCache(redis)
        key = f"{_CODE_PREFIX}:{code_type}:{email}"
        stored = await cache.get(key)

        if not stored:
            return False, "验证码已过期，请重新获取"
        if stored != input_code:
            return False, "验证码错误"

        await cache.delete(key)
        return True, ""
