"""邮件服务"""
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
import string
from typing import Optional

from .config import get_settings
from .redis import RedisCache, get_redis

settings = get_settings()


class EmailService:
    """邮件发送服务"""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: Optional[str] = None,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr or username

    async def send_code(self, to_email: str, code: str, expire_minutes: int = 5):
        """发送验证码邮件"""
        message = MIMEMultipart("alternative")
        message["From"] = self.from_addr
        message["To"] = to_email
        message["Subject"] = "您的验证码"

        html = f"""
        <html>
        <body>
            <p>您的验证码是: <strong style="font-size: 24px;">{code}</strong></p>
            <p>有效期 {expire_minutes} 分钟，请勿泄露给他人。</p>
        </body>
        </html>
        """
        message.attach(MIMEText(html, "html"))

        await aiosmtplib.send(
            message,
            hostname=self.smtp_host,
            port=self.smtp_port,
            username=self.username,
            password=self.password,
        )


def generate_code(length: int = 6) -> str:
    """生成随机验证码"""
    return "".join(random.choices(string.digits, k=length))


async def send_verification_code(
    email: str,
    email_type: str,
    expire_minutes: int = 5,
) -> str:
    """发送验证码并存储到 Redis"""
    code = generate_code()

    # 存储到 Redis
    redis = await get_redis()
    cache = RedisCache(redis)
    key = f"email_code:{email_type}:{email}"
    await cache.set(code, expire=expire_minutes * 60)

    # 发送邮件
    email_service = EmailService(
        smtp_host=settings.SMTP_HOST,
        smtp_port=settings.SMTP_PORT,
        username=settings.SMTP_USERNAME,
        password=settings.SMTP_PASSWORD,
        from_addr=settings.SMTP_FROM,
    )

    await email_service.send_code(email, code, expire_minutes)
    return code
