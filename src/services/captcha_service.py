"""图形验证码服务"""
import io
import random
import string
import base64
import uuid
from typing import Tuple
from datetime import timedelta

from PIL import Image, ImageDraw, ImageFont

from src.infra.redis import get_redis


class CaptchaService:
    """图形验证码服务"""

    # 验证码字符集
    CHARSET = string.digits + string.ascii_uppercase
    CAPTCHA_LENGTH = 4
    IMAGE_SIZE = (120, 40)
    CAPTCHA_EXPIRE = 300  # 5分钟

    @staticmethod
    def _generate_code(length: int = None) -> str:
        """生成随机验证码"""
        length = length or CaptchaService.CAPTCHA_LENGTH
        return ''.join(random.choices(CaptchaService.CHARSET, k=length))

    @staticmethod
    def _generate_captcha_image(code: str) -> Image.Image:
        """生成验证码图片"""
        width, height = CaptchaService.IMAGE_SIZE
        image = Image.new('RGB', (width, height), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)

        # 尝试加载字体，如果失败使用默认字体
        try:
            # 使用系统字体，Ubuntu 常见路径
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 24)
            except (OSError, IOError):
                font = ImageFont.load_default()

        # 绘制验证码文字
        x_start = 10
        for i, char in enumerate(code):
            x = x_start + i * 25
            y = random.randint(5, 10)
            # 随机颜色
            color = (
                random.randint(0, 100),
                random.randint(0, 100),
                random.randint(0, 150),
            )
            draw.text((x, y), char, font=font, fill=color)

        # 添加干扰线
        for _ in range(3):
            x1 = random.randint(0, width)
            y1 = random.randint(0, height)
            x2 = random.randint(0, width)
            y2 = random.randint(0, height)
            draw.line(
                [(x1, y1), (x2, y2)],
                fill=(random.randint(150, 200), random.randint(150, 200), random.randint(150, 200)),
                width=1,
            )

        # 添加噪点
        for _ in range(30):
            x = random.randint(0, width)
            y = random.randint(0, height)
            draw.point((x, y), fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))

        return image

    @classmethod
    async def generate_captcha(cls) -> Tuple[str, str]:
        """
        生成验证码并存储到 Redis
        Returns: (captcha_id, base64_image)
        """
        code = cls._generate_code()
        captcha_id = f"captcha:{uuid.uuid4().hex}"

        # 生成图片
        image = cls._generate_captcha_image(code)

        # 转换为 base64
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        base64_image = base64.b64encode(buffer.getvalue()).decode()

        # 存储到 Redis
        redis = await get_redis()
        await redis.set(captcha_id, code.lower(), ex=cls.CAPTCHA_EXPIRE)

        return captcha_id, base64_image

    @classmethod
    async def verify_captcha(cls, captcha_id: str, code: str) -> bool:
        """
        验证验证码
        Returns: True if valid, False otherwise
        """
        redis = await get_redis()
        stored_code = await redis.get(captcha_id)

        if not stored_code:
            return False

        # 删除已使用的验证码（一次性）
        await redis.delete(captcha_id)

        return stored_code == code.lower()

    @classmethod
    async def validate_captcha(cls, captcha_id: str, code: str) -> Tuple[bool, str]:
        """
        验证验证码，返回 (是否有效, 错误信息)
        """
        if not captcha_id or not code:
            return False, "验证码不能为空"

        is_valid = await cls.verify_captcha(captcha_id, code)

        if not is_valid:
            return False, "验证码错误或已过期"

        return True, ""
