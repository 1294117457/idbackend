"""模板管理路由（v4 设计）

REST 接口约定：
- 前缀：/api/bonus-template
- 路由层只做三件事：接 DTO → 调 service → 包 R 响应
- **零 try/except**：业务异常由全局 exception_handlers 自动翻译
- DTO ↔ ORM 转换由 schema 完成（to_orm / apply_to）

权限码（seed_permissions.py 中注册）：
  template:list   - GET /list
  template:detail - GET /{id}
  template:create - POST /save  （v5：原 /api/bonus-template POST 路径保留兼容）
  template:update - POST /update（v5：原 /api/bonus-template/{id} PUT 路径保留兼容）
  template:delete - POST /delete（v5：原 /api/bonus-template/{id} DELETE 路径保留兼容）
  template:bind_rule - POST /{id}/rules
  template:unbind_rule - DELETE /{id}/rules/{rule_id}

v5 增量（action-style 统一接口）：
- POST /save    新建 template + 一次性绑 rule（templateId 不在 body 内）
- POST /update  编辑 template + 重置 rule 绑定（templateId 在 body 内）
- POST /delete  删除 template（templateId 在 body 内）
- 三个接口都用 POST，便于前端统一通过"复合请求体"完成动作
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app import response as R
from src.app.schemas.template import (
    TemplateCreateRequest,
    TemplateUpdateRequest,
    TemplateListQueryRequest,
    TemplateCategoryListQueryRequest,
    TemplateVO,
    TemplateDetailVO,
    TemplateListVO,
    TemplateBindRuleRequest,
    TemplateBindRuleResultVO,
    TemplateSaveRequest,
    TemplateSaveUpdateRequest,
    TemplateDeleteRequest,
    TemplateSaveResponse,
    RuleDetailVO,
    AttributeVO,
)
from src.services import TemplateService

router = APIRouter(prefix="/api/bonus-template", tags=["模板"])


# ============================================================
# 读接口
# ============================================================

@router.get("/list")
async def list_templates(
    req: Annotated[TemplateListQueryRequest, Query()],
    db: AsyncSession = Depends(get_db),
):
    """分页列表（Page[TemplateVO]）"""
    templates, total = await TemplateService.list_paged(db, req)
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
):
    """按分类列出模板（学生端选 template 用）"""
    templates = await TemplateService.list_by_category(db, req.categoryId)
    return R.query_resp([TemplateVO.from_orm_to_vo(t).model_dump() for t in templates])


@router.get("/{template_id}")
async def get_template_detail(
    template_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """模板详情（含完整规则树 + is_mixed_type 软提示）

    使用 selectinload 一次性 JOIN 完整数据（template → rules → attributes），
    共 3 条 SELECT（与 rule / attribute 数量无关）。
    """
    template = await TemplateService.get_with_rules(db, template_id)

    # ORM → VO 投影
    rule_vos = []
    for rule in sorted(template.rules, key=lambda r: r.sort_order):
        attr_vos = [
            AttributeVO.from_orm_to_vo(a)
            for a in sorted(rule.attributes, key=lambda a: a.sort_order)
        ]
        rule_vos.append(RuleDetailVO.from_orm_to_vo(rule, attr_vos))

    is_mixed = await TemplateService.is_mixed_type(db, template_id)
    vo = TemplateDetailVO.from_orm_to_vo(template, rule_vos, is_mixed)

    return R.query_resp(vo.model_dump())


# ============================================================
# 写接口
# ============================================================

@router.post("", status_code=201)
async def create_template(
    req: TemplateCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建模板（DTO 直接交给 service：to_orm() 处理 ORM 构造）"""
    template = await TemplateService.create(db, req)
    return R.created_resp(
        TemplateVO.from_orm_to_vo(template).model_dump(),
        msg="模板创建成功",
    )


@router.put("/{template_id}")
async def update_template(
    template_id: int = Path(..., ge=1),
    req: TemplateUpdateRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    """修改模板。DTO 整体交给 service：apply_to() 处理非空字段。"""
    template = await TemplateService.update(db, template_id, req)
    return R.success_resp(
        TemplateVO.from_orm_to_vo(template).model_dump(),
        msg="更新成功",
    )


@router.delete("/{template_id}")
async def delete_template(
    template_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """删除模板（级联清理 template_rule 行）"""
    await TemplateService.delete(db, template_id)
    return R.success_resp(msg="删除成功")


# ============================================================
# 关联操作
# ============================================================

@router.post("/{template_id}/rules", status_code=200)
async def bind_rule(
    template_id: int = Path(..., ge=1),
    req: TemplateBindRuleRequest = ...,
    db: AsyncSession = Depends(get_db),
):
    """绑定 rule 到 template（v4 软提示策略）。

    返回 { bound, is_mixed_type }：
    - is_mixed_type=True 时前端应弹确认框软提示（业务合法）
    """
    result = await TemplateService.bind_rule(db, template_id, req.ruleId)
    return R.success_resp(
        TemplateBindRuleResultVO(**result).model_dump(),
        msg="绑定成功",
    )


@router.delete("/{template_id}/rules/{rule_id}")
async def unbind_rule(
    template_id: int = Path(..., ge=1),
    rule_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """解绑 rule"""
    await TemplateService.unbind_rule(db, template_id, rule_id)
    return R.success_resp(msg="解绑成功")


# ============================================================
# v5 action-style 统一接口
# ============================================================

@router.post("/save")
async def save_template_with_rules(
    req: TemplateSaveRequest,
    db: AsyncSession = Depends(get_db),
):
    """v5：新建 template + 一次性绑 rule（POST 单入口）

    请求体不含 templateId（新建场景下不存在）。
    整个操作在 service 内一个事务里完成（template 落盘 + rule 全量替换）。
    """
    result = await TemplateService.save_template(db, req)
    return R.success_resp(
        result.model_dump(),
        msg="保存成功",
    )


@router.post("/update")
async def update_template_with_rules(
    req: TemplateSaveUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """v5：编辑 template + 重置 rule 绑定（POST 单入口）

    请求体含 templateId（必填），service 校验存在性。
    ruleIds 为全量，DIFF 语义生效（删除不在列表里的、新增列表里没有的）。
    """
    result = await TemplateService.update_template(db, req)
    return R.success_resp(
        result.model_dump(),
        msg="更新成功",
    )


@router.post("/delete")
async def delete_template_by_id(
    req: TemplateDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """v5：删除 template（POST 单入口）

    请求体含 templateId（必填），service 校验未关闭的 application 数量。
    """
    await TemplateService.delete_template_by_id(db, req)
    return R.success_resp(msg="删除成功")