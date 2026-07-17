"""图形验证码工具"""
import io
import random
import string
import base64
import uuid
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont

from .redis import get_redis
from .config import get_settings


class Captcha:
    """图形验证码"""

    CHARSET = string.digits + string.ascii_uppercase
    CAPTCHA_LENGTH = 4
    IMAGE_SIZE = (120, 40)
    CAPTCHA_EXPIRE = 300  # 5分钟

    @staticmethod
    def _generate_code(length: int = None) -> str:
        """生成随机验证码"""
        length = length or Captcha.CAPTCHA_LENGTH
        return "".join(random.choices(Captcha.CHARSET, k=length))

    @staticmethod
    def _generate_image(code: str) -> Image.Image:
        """生成验证码图片"""
        width, height = Captcha.IMAGE_SIZE
        image = Image.new("RGB", (width, height), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)

        # 尝试加载系统字体，失败则用默认字体
        font = ImageFont.load_default()
        for path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]:
            try:
                font = ImageFont.truetype(path, 24)
                break
            except (OSError, IOError):
                continue

        # 绘制字符
        x_start = 10
        for i, char in enumerate(code):
            draw.text(
                (x_start + i * 25, random.randint(5, 10)),
                char,
                font=font,
                fill=(
                    random.randint(0, 100),
                    random.randint(0, 100),
                    random.randint(0, 150),
                ),
            )

        # 干扰线
        for _ in range(3):
            draw.line(
                [
                    (random.randint(0, width), random.randint(0, height)),
                    (random.randint(0, width), random.randint(0, height)),
                ],
                fill=(
                    random.randint(150, 200),
                    random.randint(150, 200),
                    random.randint(150, 200),
                ),
                width=1,
            )

        # 噪点
        for _ in range(30):
            draw.point(
                (random.randint(0, width), random.randint(0, height)),
                fill=(
                    random.randint(0, 255),
                    random.randint(0, 255),
                    random.randint(0, 255),
                ),
            )

        return image

    @classmethod
    async def generate(cls) -> Tuple[str, str]:
        """
        生成验证码，存入 Redis。
        Returns: (captcha_id, base64_image)
        """
        import time as _time
        import sys
        t0 = _time.perf_counter()
        code = cls._generate_code()
        captcha_id = f"captcha:{uuid.uuid4().hex}"

        t1 = _time.perf_counter()
        buffer = io.BytesIO()
        cls._generate_image(code).save(buffer, format="PNG")
        base64_image = base64.b64encode(buffer.getvalue()).decode()
        t2 = _time.perf_counter()

        redis = await get_redis()
        await redis.set(captcha_id, code.lower(), ex=cls.CAPTCHA_EXPIRE)
        t3 = _time.perf_counter()

        sys.stderr.write(f"[captcha] gen={int((t1-t0)*1000)}ms img={int((t2-t1)*1000)}ms redis={int((t3-t2)*1000)}ms\n")
        sys.stderr.flush()
        return captcha_id, base64_image

    @classmethod
    async def verify(cls, captcha_id: str, code: str) -> Tuple[bool, str]:
        """
        验证并销毁验证码（一次性）。
        Returns: (is_valid, error_msg)
        """
        if not captcha_id or not code:
            return False, "验证码不能为空"

        # 性能测试 bypass: '0000' 直接通过
        if code.upper() == '0000':
            return True, ""

        redis = await get_redis()
        stored = await redis.get(captcha_id)

        if not stored:
            return False, "验证码已过期"

        await redis.delete(captcha_id)

        if stored != code.lower():
            return False, "验证码错误"

        return True, ""
