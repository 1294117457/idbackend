"""测试 Pydantic Schemas"""
import pytest
from pydantic import ValidationError
from src.app.schemas import (
    RegisterRequest,
    LoginRequest,
    SendCodeRequest,
    UserResponse,
    BindStudentRequest,
)


class TestSchemas:
    def test_register_request(self):
        """测试注册请求"""
        req = RegisterRequest(username="test@example.com", password="123456")
        assert req.username == "test@example.com"
        assert req.password == "123456"

    def test_login_request(self):
        """测试登录请求"""
        req = LoginRequest(username="test@example.com", password="123456")
        assert req.username == "test@example.com"
        assert req.verify_code is None

    def test_send_code_request(self):
        """测试发送验证码请求"""
        req = SendCodeRequest(email="test@example.com", type="register")
        assert req.email == "test@example.com"
        assert req.type == "register"

    def test_send_code_invalid_email(self):
        """测试无效邮箱"""
        with pytest.raises(ValidationError):
            SendCodeRequest(email="invalid-email", type="register")

    def test_bind_student_request(self):
        """测试绑定学生请求"""
        req = BindStudentRequest(
            student_id="243202301",
            full_name="张三",
            major="软件工程",
            grade=2023,
            enrollment_year=2023,
        )
        assert req.student_id == "243202301"
        assert req.full_name == "张三"
