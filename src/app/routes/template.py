"""模板管理路由

接口约定：
- 前缀：/api/bonus-template
- 路由层只做三件事：接 DTO → 调 service → 包 R 响应
- **零 try/except**：业务异常由全局 exception_handlers 自动翻译
- DTO ↔ ORM 转换由 schema 完成（to_orm / apply_to）

权限码（init_rbac_data.py 中注册）：
  template:list        - GET /list, /by-category
  template:detail      - GET /detail
  template:create      - POST /save
  template:update      - POST /update
  template:delete      - POST /delete
  template:bind_rule   - POST /bind-rule
  template:unbind_rule - POST /unbind-rule
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.services import TemplateService
from src.infra.rich_text_service import RichTextService
from src.app.dependencies import get_db, get_storage, get_rich_text_service
from src.infra.storage import Storage
from src.app import response as R
from src.app.schemas.template import (
    TemplateListQueryRequest,
    TemplateCategoryListQueryRequest,
    TemplateVO,
    TemplateDetailVO,
    TemplateListVO,
    TemplateBindRuleRequest,
    TemplateUnbindRuleRequest,
    TemplateBindRuleResultVO,
    TemplateSaveRequest,
    TemplateSaveUpdateRequest,
    TemplateDeleteRequest,
    TemplateSaveResponse,
)

router = APIRouter(prefix="/api/bonus-template", tags=["模板"])


# ============================================================
# 读接口
# ============================================================

@router.get("/list")
async def list_templates(
    req: Annotated[TemplateListQueryRequest, Query()],
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
    rich_text_service: RichTextService = Depends(get_rich_text_service),
):
    """分页列表（Page[TemplateVO]）

    v9：后端在返回前对 description 做"占位 → 预签名 URL"批量替换。
    """
    templates, total = await TemplateService.list_paged(
        db, storage, rich_text_service, req,
    )
    items = [TemplateVO.from_orm_to_vo(t) for t in templates]
    vo = TemplateListVO.from_list_to_page(
        items=items,
        total=total,
        page_num=req.pageNum,
        page_size=req.pageSize,
    )
    return R.query_resp(vo.model_dump())


@router.get("/by-category")
async def list_templates_by_category(
    req: Annotated[TemplateCategoryListQueryRequest, Query()],
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
    rich_text_service: RichTextService = Depends(get_rich_text_service),
):
    """按分类列出模板（学生端选 template 用）

    v9：返回前做富文本占位替换。
    """
    templates = await TemplateService.list_by_category(
        db, storage, rich_text_service, req.categoryId,
    )
    return R.query_resp([TemplateVO.from_orm_to_vo(t).model_dump() for t in templates])


@router.get("/detail")
async def get_template_detail(
    id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
    rich_text_service: RichTextService = Depends(get_rich_text_service),
):
    """模板详情（含完整规则树 + is_mixed_type 软提示）"""
    template = await TemplateService.get_with_rules(
        db, storage, rich_text_service, id,
    )
    is_mixed = await TemplateService.is_mixed_type(db, id)

    sorted_rules = sorted(template.rules, key=lambda r: r.sort_order)
    vo = TemplateDetailVO.from_template_with_rules(template, sorted_rules, is_mixed)

    return R.query_resp(vo.model_dump())


# ============================================================
# 关联操作
# ============================================================

@router.post("/bind-rule")
async def bind_rule(
    req: TemplateBindRuleRequest,
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
    rich_text_service: RichTextService = Depends(get_rich_text_service),
):
    """绑定 rule 到 template"""
    result = await TemplateService.bind_rule(
        db, storage, rich_text_service, req.templateId, req.ruleId,
    )
    return R.success_resp(
        TemplateBindRuleResultVO(**result).model_dump(),
        msg="绑定成功",
    )


@router.post("/unbind-rule")
async def unbind_rule(
    req: TemplateUnbindRuleRequest,
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
    rich_text_service: RichTextService = Depends(get_rich_text_service),
):
    """解绑 rule"""
    await TemplateService.unbind_rule(
        db, storage, rich_text_service, req.templateId, req.ruleId,
    )
    return R.success_resp(msg="解绑成功")


# ============================================================
# v5 action-style 统一接口
# ============================================================

@router.post("/save")
async def save_template_with_rules(
    req: TemplateSaveRequest,
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
    rich_text_service: RichTextService = Depends(get_rich_text_service),
):
    """v5：新建 template + 一次性绑 rule（POST 单入口）

    请求体不含 templateId（新建场景下不存在）。
    整个操作在 service 内一个事务里完成（template 落盘 + rule 全量替换）。
    v9：返回前对 description 做占位替换。
    """
    result = await TemplateService.save_template(db, storage, rich_text_service, req)
    return R.success_resp(
        result.model_dump(),
        msg="保存成功",
    )


@router.post("/update")
async def update_template_with_rules(
    req: TemplateSaveUpdateRequest,
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
    rich_text_service: RichTextService = Depends(get_rich_text_service),
):
    """v5：编辑 template + 重置 rule 绑定（POST 单入口）

    请求体含 templateId（必填），service 校验存在性。
    ruleIds 为全量，DIFF 语义生效（删除不在列表里的、新增列表里没有的）。
    v9：返回前对 description 做占位替换。
    """
    result = await TemplateService.update_template(db, storage, rich_text_service, req)
    return R.success_resp(
        result.model_dump(),
        msg="更新成功",
    )


@router.post("/delete")
async def delete_template_by_id(
    req: TemplateDeleteRequest,
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
    rich_text_service: RichTextService = Depends(get_rich_text_service),
):
    """v5：删除 template（POST 单入口）

    请求体含 templateId（必填），不再校验 application 数量（允许删除有申请的模板）。
    删除时级联清理富文本文件（MinIO，按 prefix）。
    """
    await TemplateService.delete_template_by_id(
        db, storage, rich_text_service, req,
    )
    return R.success_resp(msg="删除成功")