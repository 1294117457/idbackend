"""Step 2 测试：验证 repo 不再有 commit/rollback/refresh helper，且 service 不再调用它们。

运行：
    cd idbackend && pytest tests/test_repos_no_commit.py -v

依据：
    docs/docs-backend/dbremake/step2-repo-cleanup.md
    （注意：本项目实际有 40+ 处 service 调用 repo helper，
     所以 Step 2 实际做了"把 service 调用方改成 await db.commit()/refresh()
     + 删除 repo helper"，与原文档略不同，详见 step2-repo-cleanup.md 修订版）
"""
import ast
import pathlib

import pytest

# ─── 受影响的 repo 列表 ────────────────────────────────────────
REPO_FILES = [
    "src/repositories/ai_chat_repo.py",
    "src/repositories/embedding_repo.py",
    "src/repositories/application_repo.py",
    "src/repositories/template_repo.py",
    "src/repositories/template_category_repo.py",
    "src/repositories/extra_info_field_repo.py",
    "src/repositories/attribute_repo.py",
    "src/repositories/rule_repo.py",
]


# ─── 测试 1：每个 repo 文件都不包含 commit/rollback/refresh helper ────
@pytest.mark.step2
@pytest.mark.parametrize("repo_file", REPO_FILES)
def test_repo_has_no_helper_methods(repo_file):
    """确保 repo 没有定义 commit/rollback/refresh 静态方法。"""
    file_path = pathlib.Path(repo_file)
    assert file_path.exists(), f"{repo_file} 不存在"

    source = file_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            if node.name in ("commit", "rollback", "refresh"):
                # 检查函数参数：第一个参数必须是 db: AsyncSession
                if node.args.args and node.args.args[0].arg == "db":
                    pytest.fail(
                        f"{repo_file}:{node.lineno} 仍然定义了 {node.name}(db) helper，"
                        f"应该删除（事务由 get_db 统一管理）"
                    )


# ─── 测试 2：全项目没有人调用 xxxRepository.commit/rollback/refresh ──────
@pytest.mark.step2
def test_no_one_calls_repo_helper_methods():
    """确保没人调用 xxxRepository.commit/rollback/refresh()。"""
    import subprocess

    repos = (
        "AIChatRepository|EmbeddingRepository|ApplicationRepository|"
        "TemplateRepository|TemplateCategoryRepository|ExtraInfoFieldRepository|"
        "AttributeRepository|RuleRepository"
    )
    result = subprocess.run(
        [
            "rg", "--type", "py", "-l",
            f"({repos})\\.(commit|rollback|refresh)\\(",
        ],
        capture_output=True,
        text=True,
        cwd=pathlib.Path("src"),
    )
    matches = result.stdout.strip().split("\n") if result.stdout.strip() else []
    assert matches == [], (
        f"发现残留调用方:\n{chr(10).join(matches)}\n"
        f"Step 2 要求 service 直接用 db.commit() / db.refresh()，不通过 repo helper"
    )


# ─── 测试 3：repo 模块可以正常 import ─────────────────────────
@pytest.mark.step2
def test_repos_can_be_imported():
    """删除代码后 repo 模块语法没问题。"""
    from src.repositories import (
        ai_chat_repo,
        embedding_repo,
        application_repo,
        template_repo,
        template_category_repo,
        extra_info_field_repo,
        attribute_repo,
        rule_repo,
    )
    # 确保这些模块有预期的 repo 类
    assert hasattr(ai_chat_repo, "AIChatRepository")
    assert hasattr(embedding_repo, "EmbeddingRepository")
    assert hasattr(application_repo, "ApplicationRepository")
    assert hasattr(template_repo, "TemplateRepository")
    assert hasattr(template_category_repo, "TemplateCategoryRepository")
    assert hasattr(extra_info_field_repo, "ExtraInfoFieldRepository")
    assert hasattr(attribute_repo, "AttributeRepository")
    assert hasattr(rule_repo, "RuleRepository")
    # 确保这些类没有 commit/rollback/refresh 属性
    for cls_name, cls in [
        ("AIChatRepository", ai_chat_repo.AIChatRepository),
        ("EmbeddingRepository", embedding_repo.EmbeddingRepository),
        ("ApplicationRepository", application_repo.ApplicationRepository),
        ("TemplateRepository", template_repo.TemplateRepository),
        ("TemplateCategoryRepository", template_category_repo.TemplateCategoryRepository),
        ("ExtraInfoFieldRepository", extra_info_field_repo.ExtraInfoFieldRepository),
        ("AttributeRepository", attribute_repo.AttributeRepository),
        ("RuleRepository", rule_repo.RuleRepository),
    ]:
        for method in ("commit", "rollback", "refresh"):
            assert not hasattr(cls, method), (
                f"{cls_name} 还有 {method} 方法，应该删除"
            )


# ─── 测试 4：service 不再调用 xxxRepository.commit/refresh ──────
@pytest.mark.step2
def test_services_dont_use_repo_helper_methods():
    """service 层不应该再用 repo helper（应该直接 await db.commit() / db.refresh()）。"""
    import subprocess

    repos = (
        "AIChatRepository|EmbeddingRepository|ApplicationRepository|"
        "TemplateRepository|TemplateCategoryRepository|ExtraInfoFieldRepository|"
        "AttributeRepository|RuleRepository"
    )
    result = subprocess.run(
        [
            "rg", "--type", "py",
            f"({repos})\\.(commit|rollback|refresh)\\(",
        ],
        capture_output=True,
        text=True,
        cwd=pathlib.Path("src"),
    )
    matches = result.stdout.strip().split("\n") if result.stdout.strip() else []
    assert matches == [], (
        f"service 还在调用 repo helper:\n{chr(10).join(matches)}\n"
        f"Step 2 应该改成 await db.commit() / await db.refresh()"
    )


# ─── 测试 5：service 都不再有 commit（Step 3+5+6 后）────────
@pytest.mark.step2
def test_services_have_no_db_commit():
    """Step 3+5+6 后，所有 service 都不应该再有 commit 调用。

    事务由 get_db / get_db_context 框架统一管理。
    """
    import subprocess
    result = subprocess.run(
        [
            "rg", "--type", "py",
            r"await (db|self\._db)\.commit\(\)",
        ],
        capture_output=True,
        text=True,
        cwd=pathlib.Path("src/services"),
    )
    matches = result.stdout.strip().split("\n") if result.stdout.strip() else []
    assert matches == [], (
        f"service 还在调 commit:\n{chr(10).join(matches)}\n"
        f"Step 3+5+6 后所有 commit 应该由框架处理"
    )
