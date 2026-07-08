# idpython 完善设计文档

> 基于 idbackend 旧工程功能分析 + idfrontend/idfrontend-admin 前端 API 调用分析
> **目标**: 确保 idpython 修改后与旧工程和前后端完全兼容

## 目录

1. [完整 API 路径对照表](#1-完整-api-路径对照表)
2. [前端依赖分析](#2-前端依赖分析)
3. [API 详细设计](#3-api-详细设计)
4. [数据库模型调整](#4-数据库模型调整)
5. [Service 层代码实现](#5-service-层代码实现)
6. [业务逻辑说明](#6-业务逻辑说明)
7. [实现优先级](#7-实现优先级)

---

## 1. 完整 API 路径对照表

### 1.1 模板管理 `/api/bonus-template`

| 前端调用 | 后端路径 | 方法 | 状态 | 备注 |
|----------|----------|------|------|------|
| `getTemplateList()` | `/api/bonus-template/list` | GET | ✅ 已有 | |
| `getTemplateDetail(id)` | `/api/bonus-template/{templateId}` | GET | ✅ 已有 | |
| `createTemplate(data)` | `/api/bonus-template/create` | POST | ✅ 已有 | |
| `updateTemplate(id, data)` | `/api/bonus-template/{templateId}` | PUT | ❌ 需补充 | 含规则重建 |
| `deleteTemplate(id)` | `/api/bonus-template/{templateId}` | DELETE | ❌ 需补充 | 含规则删除 |

### 1.2 属性管理 `/api/rule-attribute`

| 前端调用 | 后端路径 | 方法 | 状态 | 备注 |
|----------|----------|------|------|------|
| `getAllAttributes()` | `/api/rule-attribute/list` | GET | ❌ 需补充 | |
| `getAttributesByType(type)` | `/api/rule-attribute/list-by-type/{type}` | GET | ❌ 需补充 | |
| `getAttributesByCode(code)` | `/api/rule-attribute/list-by-code/{code}` | GET | ❌ 需补充 | |
| `getAttributeDetail(id)` | `/api/rule-attribute/{id}` | GET | ❌ 需补充 | |
| `createAttribute(data)` | `/api/rule-attribute/create` | POST | ❌ 需补充 | |
| `updateAttribute(id, data)` | `/api/rule-attribute/{id}` | PUT | ❌ 需补充 | |
| `deleteAttribute(id)` | `/api/rule-attribute/{id}` | DELETE | ❌ 需补充 | |

### 1.3 证明材料管理 `/api/proof`

| 前端调用 | 后端路径 | 方法 | 状态 | 备注 |
|----------|----------|------|------|------|
| `getApplicationProofs(applicationId)` | `/api/proof/list/{applicationId}` | GET | ❌ 需补充 | |
| `approveProof(proofId, comment)` | `/api/proof/{proofId}/approve` | POST | ❌ 需补充 | |
| `rejectProof(proofId, comment)` | `/api/proof/{proofId}/reject` | POST | ❌ 需补充 | |
| `addProof(applicationId, data)` | `/api/proof/application/{applicationId}` | POST | ❌ 需补充 | |
| `resubmitProof(proofId, data)` | `/api/proof/{proofId}/resubmit` | PUT | ❌ 需补充 | |
| `overrideProof(proofId, status, comment)` | `/api/proof/{proofId}/override` | PUT | ❌ 需补充 | |

### 1.4 申请管理 `/api/application`

| 前端调用 | 后端路径 | 方法 | 状态 | 备注 |
|----------|----------|------|------|------|
| `submitApplication(data)` | `/api/application/submit` | POST | ✅ 已有 | |
| `getMyRecords()` | `/api/application/my-records` | GET | ✅ 已有 | |
| `cancelRecord(recordId)` | `/api/application/cancel/{recordId}` | DELETE | ⚠️ 已禁用 | 返回 403 |
| `resubmitApplication(recordId)` | `/api/application/resubmit/{recordId}` | POST | ✅ 已有 | |
| `getPendingRecordsPaged(...)` | `/api/application/audit/pending` | GET | ❌ 需补充 | 分页+筛选 |
| `getAuditHistoryPaged(...)` | `/api/application/audit/history` | GET | ❌ 需补充 | 分页+筛选 |
| `approveRecord(data)` | `/api/application/audit/approve` | POST | ✅ 已有 | |
| `rejectRecord(data)` | `/api/application/audit/reject` | POST | ✅ 已有 | |
| `revokeRecord(data)` | `/api/application/audit/revoke` | POST | ❌ 需补充 | |

### 1.5 需求模板 `/api/demand-template`

| 前端调用 | 后端路径 | 方法 | 状态 | 备注 |
|----------|----------|------|------|------|
| `getActiveTemplates()` | `/api/demand-template/active` | GET | ❌ 需补充 | 学生端 |
| `getAllTemplates()` | `/api/demand-template/list` | GET | ❌ 需补充 | 管理端 |
| `createTemplate(data)` | `/api/demand-template/create` | POST | ❌ 需补充 | |
| `updateTemplate(id, data)` | `/api/demand-template/{id}` | PUT | ❌ 需补充 | |
| `deleteTemplate(id)` | `/api/demand-template/{id}` | DELETE | ❌ 需补充 | |

### 1.6 需求申请 `/api/demand-application`

| 前端调用 | 后端路径 | 方法 | 状态 | 备注 |
|----------|----------|------|------|------|
| `saveDemandApplicationWithFileIds(...)` | `/api/demand-application/submit` | POST | ❌ 需补充 | |
| `getMyDemandApplication()` | `/api/demand-application/my` | GET | ❌ 需补充 | |
| `deleteMyDemandApplication()` | `/api/demand-application/my` | DELETE | ❌ 需补充 | |
| `getAllDemandApplications()` | `/api/demand-application/all` | GET | ❌ 需补充 | |

### 1.7 字段配置 `/api/field-config`

| 前端调用 | 后端路径 | 方法 | 状态 | 备注 |
|----------|----------|------|------|------|
| `getFieldConfigList(type)` | `/api/field-config/list` | GET | ✅ 已有 | |
| `getAllFieldConfigs()` | `/api/field-config/list/all` | GET | ✅ 已有 | |
| `createFieldConfig(data)` | `/api/field-config` | POST | ✅ 已有 | |
| `updateFieldConfig(id, data)` | `/api/field-config/{id}` | PUT | ✅ 已有 | |
| `deleteFieldConfig(id)` | `/api/field-config/{id}` | DELETE | ✅ 已有 | |
| `getSubcategoryList(fieldId)` | `/api/field-config/subcategory/list` | GET | ✅ 已有 | |
| `createSubcategory(data)` | `/api/field-config/subcategory` | POST | ✅ 已有 | |
| `updateSubcategory(id, data)` | `/api/field-config/subcategory/{id}` | PUT | ✅ 已有 | |
| `deleteSubcategory(id)` | `/api/field-config/subcategory/{id}` | DELETE | ✅ 已有 | |

---

## 2. 前端依赖分析

### 2.1 idfrontend (学生端) 依赖

| 页面 | 依赖 API | 状态 |
|------|----------|------|
| `score/index.vue` | `/api/bonus-template/list` | ✅ |
| | `/api/bonus-template/{id}` | ✅ |
| | `/api/application/submit` | ✅ |
| | `/api/application/my-records` | ✅ |
| | `/api/proof/list/{applicationId}` | ❌ |
| | `/api/proof/{proofId}/approve` | ❌ |
| | `/api/proof/{proofId}/reject` | ❌ |
| `score/history.vue` | `/api/application/my-records` | ✅ |
| | `/api/application/cancel/{recordId}` | ⚠️ |
| | `/api/application/resubmit/{recordId}` | ✅ |
| | `/api/proof/{proofId}/resubmit` | ❌ |
| `ai-chat/index.vue` | AI 匹配相关 | 后续 |
| `demand/manage.vue` | `/api/demand-template/active` | ❌ |
| | `/api/demand-application/submit` | ❌ |
| | `/api/demand-application/my` | ❌ |

### 2.2 idfrontend-admin (管理端) 依赖

| 页面 | 依赖 API | 状态 |
|------|----------|------|
| `template/scoreTemplate.vue` | `/api/bonus-template/*` | 部分缺失 |
| | `/api/rule-attribute/*` | ❌ |
| `template/scoreAttribute.vue` | `/api/rule-attribute/*` | ❌ |
| `template/fieldConfig.vue` | `/api/field-config/*` | ✅ |
| `template/demandTemplate.vue` | `/api/demand-template/*` | ❌ |
| `score/index.vue` | `/api/application/audit/*` | 部分缺失 |
| | `/api/proof/*` | ❌ |
| `score/history.vue` | `/api/application/audit/history` | ❌ |

---

## 3. API 详细设计

### 3.1 属性管理 `/api/rule-attribute`

```python
# routes/attribute.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List
from src.app.deps import get_db, get_current_user, CurrentUser, require_admin
from src.app.response import success_response, error_response
from src.services.attribute_service import AttributeService

router = APIRouter(prefix="/api/rule-attribute", tags=["属性管理"])


class RuleAttributeRequest(BaseModel):
    attributeCode: str
    attributeType: str        # 'CONDITION' | 'TRANSFORM'
    attributeValue: str
    inputMax: Optional[float] = None
    inputMin: Optional[float] = None
    inputInterval: Optional[str] = None  # 'OPEN' | 'CLOSED' | 'LEFT_OPEN' | 'RIGHT_OPEN'
    displayOrder: int = 0
    description: Optional[str] = None
    isActive: Optional[bool] = True


@router.get("/list")
async def list_attributes(
    user: CurrentUser = Depends(require_admin),
    db=Depends(get_db),
):
    """获取所有启用的属性"""
    attrs = await AttributeService.get_all_active(db)
    return success_response([{
        "id": a.id,
        "attributeCode": a.attribute_code,
        "attributeType": a.attribute_type,
        "attributeValue": a.attribute_value,
        "inputMax": a.input_max,
        "inputMin": a.input_min,
        "inputInterval": a.input_interval,
        "displayOrder": a.display_order,
        "description": a.description,
    } for a in attrs])


@router.get("/list-by-type/{type}")
async def list_by_type(
    type: str,
    user: CurrentUser = Depends(require_admin),
    db=Depends(get_db),
):
    """根据类型获取属性"""
    attrs = await AttributeService.get_by_type(db, type)
    return success_response([format_attr(a) for a in attrs])


@router.get("/list-by-code/{code}")
async def list_by_code(
    code: str,
    user: CurrentUser = Depends(require_admin),
    db=Depends(get_db),
):
    """根据编码获取属性"""
    attrs = await AttributeService.get_by_code(db, code)
    return success_response([format_attr(a) for a in attrs])


@router.get("/{attribute_id}")
async def get_detail(
    attribute_id: int,
    user: CurrentUser = Depends(require_admin),
    db=Depends(get_db),
):
    """获取属性详情"""
    attr = await AttributeService.get_by_id(db, attribute_id)
    if not attr:
        return error_response("属性不存在", code=404)
    return success_response(format_attr(attr))


@router.post("/create")
async def create(
    data: RuleAttributeRequest,
    user: CurrentUser = Depends(require_admin),
    db=Depends(get_db),
):
    """创建属性"""
    attr = await AttributeService.create(
        db,
        attribute_code=data.attributeCode,
        attribute_type=data.attributeType,
        attribute_value=data.attributeValue,
        input_min=data.inputMin,
        input_max=data.inputMax,
        input_interval=data.inputInterval,
        display_order=data.displayOrder,
        description=data.description,
    )
    return success_response({"id": attr.id})


@router.put("/{attribute_id}")
async def update(
    attribute_id: int,
    data: RuleAttributeRequest,
    user: CurrentUser = Depends(require_admin),
    db=Depends(get_db),
):
    """更新属性"""
    try:
        attr = await AttributeService.update(
            db, attribute_id, **data.model_dump(exclude_none=True)
        )
        return success_response({"id": attr.id})
    except ValueError as e:
        return error_response(str(e), code=400)


@router.delete("/{attribute_id}")
async def delete(
    attribute_id: int,
    user: CurrentUser = Depends(require_admin),
    db=Depends(get_db),
):
    """删除属性"""
    await AttributeService.delete(db, attribute_id)
    return success_response(msg="删除成功")
```

### 3.2 证明材料管理 `/api/proof`

```python
# routes/proof.py
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
from src.app.deps import get_db, get_current_user, CurrentUser, require_reviewer
from src.app.response import success_response, error_response
from src.services.proof_service import ProofService

router = APIRouter(prefix="/api/proof", tags=["证明材料"])


class AddProofRequest(BaseModel):
    proofFileId: int
    proofValue: float = 0
    remark: Optional[str] = None
    reviewCount: Optional[int] = None


class ResubmitProofRequest(BaseModel):
    proofFileId: Optional[int] = None
    proofValue: Optional[float] = None
    remark: Optional[str] = None


@router.get("/list/{application_id}")
async def list_proofs(
    application_id: int,
    user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """获取申请的证明材料列表"""
    is_admin = user.role in ["admin", "super_admin", "reviewer"]
    proofs = await ProofService.get_by_application(
        db, application_id, None if is_admin else user.user_id
    )
    if proofs is None:
        return error_response("无权访问", code=403)
    return success_response([{
        "id": p.id,
        "applicationId": p.application_id,
        "proofFileId": p.proof_file_id,
        "proofValue": p.proof_value,
        "reviewCount": p.review_count,
        "approvedCount": p.approved_count,
        "status": p.status,
        "statusText": get_proof_status_text(p.status),
        "reviewerIds": p.reviewer_ids,
        "reviewRecords": p.review_records,
        "remark": p.remark,
        "createdAt": str(p.created_at),
    } for p in proofs])


@router.post("/{proof_id}/approve")
async def approve(
    proof_id: int,
    comment: Optional[str] = Query(None),
    user: CurrentUser = Depends(require_reviewer),
    db=Depends(get_db),
):
    """审核证明材料通过"""
    try:
        await ProofService.approve(db, proof_id, user.user_id, comment)
        return success_response(msg="审核通过")
    except ValueError as e:
        return error_response(str(e))


@router.post("/{proof_id}/reject")
async def reject(
    proof_id: int,
    comment: Optional[str] = Query(None),
    user: CurrentUser = Depends(require_reviewer),
    db=Depends(get_db),
):
    """审核证明材料驳回"""
    try:
        await ProofService.reject(db, proof_id, user.user_id, comment)
        return success_response(msg="已驳回")
    except ValueError as e:
        return error_response(str(e))


@router.post("/application/{application_id}")
async def add_proof(
    application_id: int,
    data: AddProofRequest,
    user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """追加证明材料"""
    try:
        proof = await ProofService.add(
            db, application_id, user.user_id,
            file_id=data.proofFileId,
            proof_value=data.proofValue,
            remark=data.remark,
            review_count=data.reviewCount,
        )
        return success_response({"id": proof.id})
    except PermissionError:
        return error_response("无权操作此申请", code=403)
    except ValueError as e:
        return error_response(str(e))


@router.put("/{proof_id}/resubmit")
async def resubmit(
    proof_id: int,
    data: ResubmitProofRequest,
    user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """重新提交被驳回的证明材料"""
    try:
        await ProofService.resubmit(
            db, proof_id, user.user_id,
            file_id=data.proofFileId,
            proof_value=data.proofValue,
            remark=data.remark,
        )
        return success_response(msg="重新提交成功")
    except PermissionError:
        return error_response("无权操作此证明材料", code=403)
    except ValueError as e:
        return error_response(str(e))


@router.put("/{proof_id}/override")
async def override(
    proof_id: int,
    status: int = Query(..., ge=1, le=2),
    comment: Optional[str] = Query(None),
    user: CurrentUser = Depends(require_reviewer),
    db=Depends(get_db),
):
    """审核员覆盖修改状态"""
    try:
        await ProofService.override_status(
            db, proof_id, user.user_id, status, comment
        )
        return success_response(msg="操作成功")
    except ValueError as e:
        return error_response(str(e))


def get_proof_status_text(status: int) -> str:
    return {0: "待审核", 1: "已通过", 2: "已驳回"}.get(status, "未知")
```

### 3.3 申请管理增强 `/api/application`

```python
# routes/application.py 补充

class RevokeRequest(BaseModel):
    recordId: int
    reason: str


@router.get("/audit/pending")
async def get_pending(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    studentId: Optional[str] = Query(None),
    studentName: Optional[str] = Query(None),
    major: Optional[str] = Query(None),
    user: CurrentUser = Depends(require_reviewer),
    db=Depends(get_db),
):
    """分页获取待审核列表"""
    applications, total = await ApplicationService.get_pending_paged(
        db, page, size, studentId, studentName, major
    )
    return success_response({
        "records": [format_app(a) for a in applications],
        "total": total,
    })


@router.get("/audit/history")
async def get_history(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    studentId: Optional[str] = Query(None),
    studentName: Optional[str] = Query(None),
    major: Optional[str] = Query(None),
    user: CurrentUser = Depends(require_reviewer),
    db=Depends(get_db),
):
    """分页获取审核历史"""
    applications, total = await ApplicationService.get_history_paged(
        db, page, size, studentId, studentName, major
    )
    return success_response({
        "records": [format_app(a) for a in applications],
        "total": total,
    })


@router.post("/audit/revoke")
async def revoke(
    data: RevokeRequest,
    user: CurrentUser = Depends(require_reviewer),
    db=Depends(get_db),
):
    """撤销已通过的申请"""
    result = await ApplicationService.revoke(
        db, data.recordId, user.user_id, data.reason
    )
    if not result:
        return error_response("撤销失败", code=400)
    return success_response(msg="撤销成功")


def format_app(a) -> dict:
    """格式化申请记录"""
    return {
        "id": a.id,
        "studentId": a.student_id,
        "studentName": a.student_name,
        "major": a.major,
        "enrollmentYear": a.enrollment_year,
        "templateName": a.template_name,
        "templateType": TemplateService.get_template_type(a.template_name),
        "scoreType": a.score_type,
        "applyScore": a.apply_score,
        "applyInput": a.apply_input,
        "proofsInput": a.proofs_input,
        "gainScore": a.gain_score,
        "status": a.status,
        "statusText": get_status_text(a.status),
        "submitTime": a.submit_time.strftime("%Y-%m-%d %H:%M:%S") if a.submit_time else None,
        "remark": a.remark,
        "reviewCount": a.review_count,
        "currentReviewCount": a.current_review_count,
        "reviewRecords": a.review_records,
    }


def get_status_text(status: int) -> str:
    return {0: "待审核", 1: "已通过", 2: "已驳回", 4: "已撤销"}.get(status, "未知")
```

### 3.4 需求模板 `/api/demand-template`

```python
# routes/demand_template.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List
from src.app.deps import get_db, get_current_user, CurrentUser, require_admin
from src.app.response import success_response, error_response
from src.services.demand_service import DemandTemplateService

router = APIRouter(prefix="/api/demand-template", tags=["需求模板"])


class DemandTemplateCreate(BaseModel):
    templateName: str
    conditions: Optional[List[str]] = []
    description: Optional[str] = None
    sortOrder: int = 0


class DemandTemplateUpdate(BaseModel):
    templateName: Optional[str] = None
    conditions: Optional[List[str]] = None
    description: Optional[str] = None
    sortOrder: Optional[int] = None
    isActive: Optional[bool] = None


@router.get("/active")
async def get_active(
    user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """学生端 - 获取启用的模板"""
    templates = await DemandTemplateService.get_active(db)
    return success_response([{
        "id": t.id,
        "templateName": t.template_name,
        "conditions": t.conditions,
        "description": t.description,
    } for t in templates])


@router.get("/list")
async def get_all(
    user: CurrentUser = Depends(require_admin),
    db=Depends(get_db),
):
    """管理端 - 获取所有模板"""
    templates = await DemandTemplateService.get_all(db)
    return success_response([{
        "id": t.id,
        "templateName": t.template_name,
        "conditions": t.conditions,
        "description": t.description,
        "sortOrder": t.sort_order,
        "isActive": t.is_active,
        "createdBy": t.created_by,
        "createdAt": str(t.created_at),
    } for t in templates])


@router.post("/create")
async def create(
    data: DemandTemplateCreate,
    user: CurrentUser = Depends(require_admin),
    db=Depends(get_db),
):
    """创建需求模板"""
    template = await DemandTemplateService.create(
        db,
        template_name=data.templateName,
        conditions=data.conditions,
        description=data.description,
        created_by=user.username,
        sort_order=data.sortOrder,
    )
    return success_response({"id": template.id})


@router.put("/{template_id}")
async def update(
    template_id: int,
    data: DemandTemplateUpdate,
    user: CurrentUser = Depends(require_admin),
    db=Depends(get_db),
):
    """更新需求模板"""
    template = await DemandTemplateService.update(
        db, template_id, **data.model_dump(exclude_none=True)
    )
    if not template:
        return error_response("模板不存在", code=404)
    return success_response({"id": template.id})


@router.delete("/{template_id}")
async def delete(
    template_id: int,
    user: CurrentUser = Depends(require_admin),
    db=Depends(get_db),
):
    """删除需求模板"""
    result = await DemandTemplateService.delete(db, template_id)
    if not result:
        return error_response("模板不存在", code=404)
    return success_response(msg="删除成功")
```

### 3.5 需求申请 `/api/demand-application`

```python
# routes/demand_application.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List
from src.app.deps import get_db, get_current_user, CurrentUser, require_reviewer
from src.app.response import success_response, error_response
from src.services.demand_service import DemandApplicationService

router = APIRouter(prefix="/api/demand-application", tags=["需求申请"])


class DemandApplicationItem(BaseModel):
    templateId: int
    templateName: str
    selectedCondition: Optional[str] = None
    inputValue: str


class DemandApplicationSubmit(BaseModel):
    applications: List[DemandApplicationItem]
    proofFiles: Optional[List[dict]] = None  # [{fileId, fileName}]


@router.post("/submit")
async def submit(
    data: DemandApplicationSubmit,
    user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """提交需求申请（覆盖式）"""
    try:
        await DemandApplicationService.submit(
            db, user.username, data.applications
        )
        return success_response(msg="提交成功")
    except ValueError as e:
        return error_response(str(e))


@router.get("/my")
async def get_my(
    user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """获取我的需求申请"""
    result = await DemandApplicationService.get_by_student(db, user.username)
    if not result:
        return success_response(msg="暂无申请记录")
    return success_response(result)


@router.delete("/my")
async def delete_my(
    user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """删除我的需求申请"""
    result = await DemandApplicationService.delete_by_student(db, user.username)
    if not result:
        return error_response("暂无申请记录")
    return success_response(msg="删除成功")


@router.get("/all")
async def get_all(
    user: CurrentUser = Depends(require_reviewer),
    db=Depends(get_db),
):
    """获取所有需求申请"""
    results = await DemandApplicationService.get_all(db)
    return success_response(results)
```

---

## 4. 数据库模型调整

### 4.1 唯一约束 SQL

```sql
-- field_config 唯一约束
ALTER TABLE field_config
ADD CONSTRAINT uk_key_college_year
UNIQUE (field_key, college_code, academic_year);

-- rule_attributes 唯一约束 (部分唯一)
ALTER TABLE rule_attributes
ADD CONSTRAINT uk_code_value_type
UNIQUE (attribute_code, attribute_value(100), attribute_type);

-- applications 添加字段
ALTER TABLE applications
ADD COLUMN revoke_reason VARCHAR(255) AFTER gain_score;

-- demand_applications 表结构
CREATE TABLE IF NOT EXISTS demand_applications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(255) NOT NULL,
    application_data JSON NOT NULL,
    submit_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_student_id (student_id)
);
```

### 4.2 SQLAlchemy 模型调整

```python
# models/template.py 补充

class RuleAttribute(Base, TimestampMixin):
    """规则属性表"""
    __tablename__ = "rule_attributes"

    attribute_code: Mapped[str] = mapped_column(String(50), nullable=False)
    attribute_type: Mapped[str] = mapped_column(String(20), nullable=False)
    attribute_value: Mapped[Optional[str]] = mapped_column(Text)
    input_max: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    input_min: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    input_interval: Mapped[Optional[str]] = mapped_column(String(20))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        # 部分唯一约束（MySQL 需要指定前缀长度）
        # UniqueConstraint('attribute_code', 'attribute_value', 'attribute_type',
        #                 name='uk_code_value_type'),
    )


class RuleAttributeMapping(Base, TimestampMixin):
    """规则属性关联表"""
    __tablename__ = "rule_attribute_mapping"

    rule_id: Mapped[int] = mapped_column(
        ForeignKey("score_template_rules.id", ondelete="CASCADE")
    )
    attribute_id: Mapped[int] = mapped_column(
        ForeignKey("rule_attributes.id", ondelete="CASCADE")
    )
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint('rule_id', 'attribute_id', name='uk_rule_attribute'),
    )


class DemandApplication(Base, TimestampMixin):
    """需求申请表"""
    __tablename__ = "demand_applications"

    student_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    application_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    submit_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('student_id', name='uk_student_id'),
    )
```

---

## 5. Service 层代码实现

### 5.1 AttributeService

```python
# services/attribute_service.py
from sqlalchemy import select, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from src.models import RuleAttribute


class AttributeService:

    @staticmethod
    async def get_all_active(db: AsyncSession) -> List[RuleAttribute]:
        result = await db.execute(
            select(RuleAttribute)
            .where(RuleAttribute.is_active == True)
            .order_by(RuleAttribute.display_order)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_type(db: AsyncSession, attr_type: str) -> List[RuleAttribute]:
        result = await db.execute(
            select(RuleAttribute)
            .where(RuleAttribute.attribute_type == attr_type)
            .where(RuleAttribute.is_active == True)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_code(db: AsyncSession, code: str) -> List[RuleAttribute]:
        result = await db.execute(
            select(RuleAttribute)
            .where(RuleAttribute.attribute_code == code)
            .where(RuleAttribute.is_active == True)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(db: AsyncSession, attr_id: int) -> Optional[RuleAttribute]:
        result = await db.execute(
            select(RuleAttribute).where(RuleAttribute.id == attr_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, **kwargs) -> RuleAttribute:
        attr = RuleAttribute(**kwargs, is_active=True)
        db.add(attr)
        await db.commit()
        await db.refresh(attr)
        return attr

    @staticmethod
    async def update(db: AsyncSession, attr_id: int, **kwargs) -> Optional[RuleAttribute]:
        attr = await AttributeService.get_by_id(db, attr_id)
        if not attr:
            return None

        # 唯一键冲突检查
        new_value = kwargs.get('attribute_value', attr.attribute_value)
        new_type = kwargs.get('attribute_type', attr.attribute_type)

        existing = await db.execute(
            select(RuleAttribute).where(
                and_(
                    RuleAttribute.attribute_code == attr.attribute_code,
                    RuleAttribute.attribute_value == new_value,
                    RuleAttribute.attribute_type == new_type,
                    RuleAttribute.id != attr_id
                )
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("该属性值已存在")

        for key, value in kwargs.items():
            if hasattr(attr, key) and value is not None:
                setattr(attr, key, value)

        await db.commit()
        await db.refresh(attr)
        return attr

    @staticmethod
    async def delete(db: AsyncSession, attr_id: int) -> bool:
        await db.execute(
            delete(RuleAttribute).where(RuleAttribute.id == attr_id)
        )
        await db.commit()
        return True
```

### 5.2 ProofService

```python
# services/proof_service.py
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime

from src.models import Application, ApplicationProof


class ProofService:

    @staticmethod
    async def get_by_application(
        db: AsyncSession,
        application_id: int,
        user_id: Optional[int] = None,
    ) -> Optional[List[ApplicationProof]]:
        if user_id:
            app = await db.execute(
                select(Application).where(Application.id == application_id)
            )
            application = app.scalar_one_or_none()
            if not application or application.user_id != user_id:
                return None  # 无权访问

        result = await db.execute(
            select(ApplicationProof)
            .where(ApplicationProof.application_id == application_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def approve(
        db: AsyncSession,
        proof_id: int,
        reviewer_id: int,
        comment: Optional[str] = None,
    ) -> ApplicationProof:
        proof = await db.get(ApplicationProof, proof_id)
        if not proof:
            raise ValueError("证明材料不存在")
        if proof.status == 1:
            raise ValueError("该证明材料已通过审核")

        # 更新审核记录
        reviewer_ids = proof.reviewer_ids or []
        if reviewer_id not in reviewer_ids:
            reviewer_ids.append(reviewer_id)

        review_records = proof.review_records or []
        review_records.append({
            "reviewerId": reviewer_id,
            "action": "approve",
            "comment": comment or "",
            "time": datetime.utcnow().isoformat(),
        })

        proof.approved_count = (proof.approved_count or 0) + 1
        proof.reviewer_ids = reviewer_ids
        proof.review_records = review_records

        if proof.approved_count >= proof.review_count:
            proof.status = 1

        await db.commit()
        await db.refresh(proof)
        return proof

    @staticmethod
    async def reject(
        db: AsyncSession,
        proof_id: int,
        reviewer_id: int,
        comment: Optional[str] = None,
    ) -> ApplicationProof:
        proof = await db.get(ApplicationProof, proof_id)
        if not proof:
            raise ValueError("证明材料不存在")
        if proof.status != 0:
            raise ValueError("该证明材料已被审核")

        reviewer_ids = proof.reviewer_ids or []
        if reviewer_id not in reviewer_ids:
            reviewer_ids.append(reviewer_id)

        review_records = proof.review_records or []
        review_records.append({
            "reviewerId": reviewer_id,
            "action": "reject",
            "comment": comment or "",
            "time": datetime.utcnow().isoformat(),
        })

        proof.reviewer_ids = reviewer_ids
        proof.review_records = review_records
        proof.status = 2

        await db.commit()
        await db.refresh(proof)
        return proof

    @staticmethod
    async def add(
        db: AsyncSession,
        application_id: int,
        user_id: int,
        file_id: int,
        proof_value: float = 0,
        remark: Optional[str] = None,
        review_count: Optional[int] = None,
    ) -> ApplicationProof:
        app = await db.get(Application, application_id)
        if not app:
            raise PermissionError("申请不存在")
        if app.user_id != user_id:
            raise PermissionError("无权操作此申请")
        if app.status != 0:
            raise ValueError("只能在待审核状态下追加证明材料")

        proof = ApplicationProof(
            application_id=application_id,
            proof_file_id=file_id,
            proof_value=proof_value,
            review_count=review_count or app.review_count,
            remark=remark,
            status=0,
        )
        db.add(proof)
        await db.commit()
        await db.refresh(proof)
        return proof

    @staticmethod
    async def resubmit(
        db: AsyncSession,
        proof_id: int,
        user_id: int,
        file_id: Optional[int] = None,
        proof_value: Optional[float] = None,
        remark: Optional[str] = None,
    ) -> ApplicationProof:
        proof = await db.get(ApplicationProof, proof_id)
        if not proof:
            raise ValueError("证明材料不存在")

        app = await db.get(Application, proof.application_id)
        if not app or app.user_id != user_id:
            raise PermissionError("无权操作此证明材料")
        if proof.status != 2:
            raise ValueError("只能重新提交已驳回的证明材料")

        if file_id:
            proof.proof_file_id = file_id
        if proof_value is not None:
            proof.proof_value = proof_value
        if remark:
            proof.remark = remark

        await db.commit()
        await db.refresh(proof)
        return proof

    @staticmethod
    async def override_status(
        db: AsyncSession,
        proof_id: int,
        reviewer_id: int,
        status: int,
        comment: Optional[str] = None,
    ) -> ApplicationProof:
        if status not in [1, 2]:
            raise ValueError("status 只能为 1（通过）或 2（驳回）")

        proof = await db.get(ApplicationProof, proof_id)
        if not proof:
            raise ValueError("证明材料不存在")

        previous_status = proof.status
        review_records = proof.review_records or []
        review_records.append({
            "reviewerId": reviewer_id,
            "action": "override_approve" if status == 1 else "override_reject",
            "comment": comment or "",
            "time": datetime.utcnow().isoformat(),
        })

        proof.status = status
        proof.approved_count = status == 1 and proof.review_count or 0
        proof.review_records = review_records

        await db.commit()
        await db.refresh(proof)
        return proof
```

---

## 6. 业务逻辑说明

### 6.1 评分计算逻辑

#### CONDITION 类型

```
规则匹配逻辑:
1. 获取模板所有规则 (按 priority 升序)
2. 遍历规则，检查所有绑定属性的输入值是否精确匹配
3. 返回第一个匹配的规则，gain_score = rule.rule_score
```

#### TRANSFORM 类型

```
公式计算逻辑:
1. 根据 input_value 找到对应的属性区间 (input_min <= input <= input_max)
2. 执行公式: eval(attribute_value.replace('INPUT', str(input_value)))
3. 返回计算结果
```

### 6.2 多审制审核

```
审核通过逻辑:
1. 检查当前审核人 < review_count
2. 添加 reviewer 记录
3. 如果 current_review_count >= review_count:
   - status = APPROVED
   - 计算 gain_score
   - 更新用户 academic_score
```

### 6.3 撤销逻辑

```
撤销逻辑:
1. 检查 status == APPROVED
2. 扣减用户 academic_score
3. 设置 status = REVOKED
4. 记录 revoke_reason
```

### 6.4 状态值对照

| Application Status | 说明 |
|-------------------|------|
| 0 | PENDING (待审核) |
| 1 | APPROVED (已通过) |
| 2 | REJECTED (已驳回) |
| 4 | REVOKED (已撤销) |

| Proof Status | 说明 |
|-------------|------|
| 0 | PENDING (待审核) |
| 1 | APPROVED (已通过) |
| 2 | REJECTED (已驳回) |

---

## 7. 实现优先级

### Phase 1: 核心 CRUD (高优先级)

| 序号 | 功能 | 文件 | 前端依赖 |
|------|------|------|----------|
| 1 | Attribute CRUD | `services/attribute_service.py` + `routes/attribute.py` | idfrontend-admin 属性管理 |
| 2 | Proof CRUD | `services/proof_service.py` + `routes/proof.py` | idfrontend-admin 审核页面 |
| 3 | Template 增强 | `routes/template.py` | idfrontend-admin 模板管理 |

### Phase 2: 申请管理增强 (高优先级)

| 序号 | 功能 | 文件 | 前端依赖 |
|------|------|------|----------|
| 4 | 分页查询 | `services/application_service.py` | idfrontend-admin 历史页面 |
| 5 | 撤销申请 | `services/application_service.py` | idfrontend-admin 审核页面 |

### Phase 3: Demand 模板 (中优先级)

| 序号 | 功能 | 文件 | 前端依赖 |
|------|------|------|----------|
| 6 | DemandTemplate CRUD | `services/demand_service.py` + `routes/demand_template.py` | idfrontend-admin |
| 7 | DemandApplication | `routes/demand_application.py` | idfrontend 学生端 |

### Phase 4: 业务逻辑完善 (后续)

| 序号 | 功能 | 说明 |
|------|------|------|
| 8 | 规则匹配 | CONDITION/TRANSFORM 自动匹配 |
| 9 | 上限校验 | FieldSubcategory 分数上限 |
| 10 | Agent 工具 | MCP 工具链集成 |

---

*文档版本: 2.0*
*生成时间: 2026-07-01*
*依据: idbackend + idfrontend + idfrontend-admin 完整源码分析*
