"""测试 JWT 功能"""
import pytest
from src.infra.jwt import create_token, verify_token, hash_password, verify_password, JWTError


class TestJWT:
    def test_hash_password(self):
        """测试密码哈希"""
        password = "test123"
        hashed = hash_password(password)

        assert hashed != password
        assert len(hashed) > 0
        assert hashed.startswith("$2b$")  # bcrypt格式

    def test_verify_password_correct(self):
        """测试验证正确密码"""
        password = "test123"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_wrong(self):
        """测试验证错误密码"""
        password = "test123"
        hashed = hash_password(password)

        assert verify_password("wrong", hashed) is False

    def test_create_token(self):
        """测试创建token"""
        token = create_token(user_id=123, username="test@example.com", role="user")

        assert token is not None
        assert len(token) > 0
        assert token.count(".") == 2  # JWT格式: header.payload.signature

    def test_verify_token(self):
        """测试验证token"""
        token = create_token(user_id=123, username="test@example.com", role="admin")
        payload = verify_token(token)

        assert payload["userId"] == 123
        assert payload["username"] == "test@example.com"
        assert payload["role"] == "admin"

    def test_verify_invalid_token(self):
        """测试验证无效token"""
        with pytest.raises(JWTError):
            verify_token("invalid.token.here")
