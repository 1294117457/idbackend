from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict

from src.models import ApplicationStatus, ProofStatus, Application, ApplicationProof
from src.app.schemas.page import Page


# ═══════════════════════════════════════════════════════════════════════
# Request DTO
# ═══════════════════════════════════════════════════════════════════════

class ProofPayload(BaseModel):
    """单条 proof（学生端编辑或审核员审核）。

    学生端（action=save/submit/edit）：
      - proofId 为 None  → 新建
      - proofId 非空      → 更新
      - fileId 为 None    → 该 proof 本轮没上传文件
      - fileId 非空且与旧值不同 → 重置 status=PENDING
      - proofScore < 0   → 字段校验失败

    审核员端（action=review/pass/reject）：
      - proofId 必填
      - status 为 APPROVED / REJECTED
      - isAdjusted 为 true 时表示老师修改过分值
    """
    model_config = ConfigDict(populate_by_name=True)

    proofId: Optional[int] = Field(default=None)
    fileId: Optional[int] = Field(default=None)
    proofScore: float = Field(ge=0, description="证明分；新建时可临时为 0")
    status: Optional[str] = Field(default=None, description="审核状态（仅审核时使用）：APPROVED / REJECTED")
    isAdjusted: bool = Field(default=False, description="是否被老师修正过（仅审核时使用）")

    def to_application_proof(self, application_id: int) -> ApplicationProof:
        """Payload → ORM ApplicationProof（新建场景）"""
        return ApplicationProof(
            application_id=application_id,
            file_id=self.fileId,
            proof_score=Decimal(str(self.proofScore)),
            status=ProofStatus.PENDING.value,
            is_adjusted=False,
        )

    def apply_to_proof(self, proof: ApplicationProof) -> None:
        """Payload → 更新已有 ApplicationProof 实例"""
        new_score = Decimal(str(self.proofScore))
        if proof.proof_score != new_score:
            proof.proof_score = new_score
        if self.fileId is not None and self.fileId != proof.file_id:
            proof.file_id = self.fileId
            proof.status = ProofStatus.PENDING.value


class ApplicationPayload(BaseModel):
    """统一申请 Payload（save / submit / edit / review 四种操作共用）。

    action 决定具体行为：
      - save       ：保存草稿（不校验 proof 完整性）
      - submit     ：新建并提交（校验 proof 完整性）
      - edit       ：编辑草稿（不校验 proof 完整性）
      - review     ：审核通过/驳回（审核员端，配合 reviewAction）

    applicationId：
      - None      → 新建
      - int       → 编辑已有申请
    """
    model_config = ConfigDict(populate_by_name=True)

    applicationId: Optional[int] = Field(default=None)
    templateId: int
    templateName: str
    categoryId: int
    applyScore: float = Field(ge=0)
    proofList: List[ProofPayload] = Field(default_factory=list)
    remark: Optional[str] = Field(default=None)
    action: str = Field(default="save", description="操作类型：save/submit/edit/review")
    reviewAction: Optional[str] = Field(default=None, description="审核动作：pass/reject（仅 action=review 时生效）")
    reviewCount: int = Field(default=1, description="审核人数，从 template 获取")

    # ★ attribute 快照（v6 新增）：{attribute.name: 用户填的值}
    # - save/submit/edit 时由前端填入，后端校验后写入
    # - 详情/列表返回时由 VO.from_orm_to_vo 读取
    attributeInfo: dict = Field(default_factory=dict, description="attribute 快照，{name: value}")

    def to_application_model(
        self,
        user_id: int,
        status: str,
    ) -> Application:
        """Payload → ORM Application（新建场景）

        Args:
            user_id: 申请人 ID
            status: 初始状态（DRAFT 或 APPLYING）
        """
        return Application(
            user_id=user_id,
            template_id=self.templateId,
            template_name=self.templateName,
            category_id=self.categoryId,
            apply_score=Decimal(str(self.applyScore)),
            gain_score=Decimal("0"),
            status=status,
            review_count=self.reviewCount or 1,
            approved_count=0,
            rejected_count=0,
            attribute_info=self.attributeInfo or {},     # ★ 新增：attribute 快照
        )

    def apply_to_model(self, app: Application, new_status: Optional[str] = None) -> None:
        """Payload → 更新已有 Application 实例

        Args:
            app: 已存在的 Application ORM 实例
            new_status: 可选，状态变更（如 DRAFT→APPLYING）
        """
        app.template_id = self.templateId
        app.template_name = self.templateName
        app.category_id = self.categoryId
        app.apply_score = Decimal(str(self.applyScore))
        app.remark = self.remark
        if self.attributeInfo is not None:
            app.attribute_info = self.attributeInfo   # ★ 新增：同步 attribute 快照
        if new_status is not None:
            app.status = new_status

    def build_proofs(self, application_id: int) -> List[ApplicationProof]:
        """Payload.proofList → List[ApplicationProof]（新建场景）"""
        return [pp.to_application_proof(application_id) for pp in self.proofList]


class ApplicationQueryRequest(BaseModel):
    """申请查询请求 DTO（my-pending / my-reviewed 等接口共用）

    命名与转换约定参考 FileQueryRequest：
      - to_conditions() → SQLAlchemy 条件列表，service 层直接 .where(*conditions)
    """
    model_config = ConfigDict(populate_by_name=True)

    fullName: Optional[str] = Field(default=None, description="学生姓名模糊匹配")
    studentId: Optional[str] = Field(default=None, description="学号前缀模糊匹配")
    templateName: Optional[str] = Field(default=None, description="模板名模糊匹配")
    status: Optional[str] = Field(default=None, description="终态过滤 PASSED/REJECTED/CANCELLED/REVOKED")
    startTime: Optional[str] = Field(default=None, description="开始时间（ISO8601）")
    endTime: Optional[str] = Field(default=None, description="结束时间（ISO8601）")
    pageNum: int = Field(default=1, ge=1, description="页码")
    pageSize: int = Field(default=20, ge=1, le=100, description="每页大小")

    def _parse_iso(self, s: Optional[str]) -> Optional[datetime]:
        """解析 ISO8601 时间字符串"""
        if not s:
            return None
        s = s.strip().replace(" ", "T")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:
                dt = datetime.fromisoformat(s.rsplit(":", 1)[0])
            except ValueError:
                return None
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    def to_conditions(self) -> list:
        """翻译为 SQLAlchemy where 条件列表

        注意：full_name / student_id 查询需要 join user 表，
        该逻辑在 service 层实现（join user_alias），
        此方法仅返回 Application 表的简单条件。
        """
        from src.models import Application
        conds: list = []
        if self.templateName:
            conds.append(Application.template_name.ilike(f"%{self.templateName}%"))
        if self.status:
            conds.append(Application.status == self.status)
        if (start := self._parse_iso(self.startTime)) is not None:
            conds.append(Application.created_at >= start)
        if (end := self._parse_iso(self.endTime)) is not None:
            conds.append(Application.created_at <= end)
        return conds


# ═══════════════════════════════════════════════════════════════════════
# Response VO
# ═══════════════════════════════════════════════════════════════════════

def _application_status_text(status: str) -> str:
    """申请状态 → 中文文本"""
    return {
        ApplicationStatus.DRAFT.value: "草稿",
        ApplicationStatus.APPLYING.value: "审核中",
        ApplicationStatus.PASSED.value: "已通过",
        ApplicationStatus.REJECTED.value: "已驳回",
        ApplicationStatus.CANCELLED.value: "已取消",
        ApplicationStatus.REVOKED.value: "已撤回",
    }.get(status, "未知")


def _proof_status_text(status: str) -> str:
    """证明状态 → 中文文本"""
    return {
        ProofStatus.PENDING.value: "待审核",
        ProofStatus.APPROVED.value: "已通过",
        ProofStatus.REJECTED.value: "已驳回",
    }.get(status, "未知")


class ProofVO(BaseModel):
    """证明材料 VO"""
    id: int
    applicationId: int
    fileId: Optional[int] = None
    fileName: Optional[str] = None
    contentType: Optional[str] = None
    fileSize: Optional[int] = None
    proofScore: float = 0
    status: str
    statusText: str
    isAdjusted: bool = False
    createdAt: Optional[str] = None

    @classmethod
    def from_orm_to_vo(cls, proof, file=None) -> "ProofVO":
        """ORM → VO 转换

        Args:
            proof: ApplicationProof ORM 对象
            file: 可选的文件元数据对象（从 relationship 或显式传入）
        """
        if file is None:
            file = getattr(proof, 'file', None)

        return cls(
            id=proof.id,
            applicationId=proof.application_id,
            fileId=proof.file_id,
            fileName=file.original_name if file else None,
            contentType=file.content_type if file else None,
            fileSize=file.file_size if file else None,
            proofScore=float(proof.proof_score) if proof.proof_score else 0,
            status=proof.status,
            statusText=_proof_status_text(proof.status),
            isAdjusted=proof.is_adjusted if hasattr(proof, 'is_adjusted') else False,
            createdAt=proof.created_at.isoformat() if proof.created_at else None,
        )


class ApplicationOperationVO(BaseModel):
    """申请操作记录 VO"""
    id: int
    applicationId: int
    operatorId: int
    operatorName: str
    operation: str
    remark: Optional[str] = None
    createdAt: Optional[str] = None

    @classmethod
    def from_orm_to_vo(cls, op) -> "ApplicationOperationVO":
        """ORM → VO 转换"""
        return cls(
            id=op.id,
            applicationId=op.application_id,
            operatorId=op.operator_id,
            operatorName=op.operator_name,
            operation=op.operation,
            remark=op.remark,
            createdAt=op.created_at.isoformat() if op.created_at else None,
        )


class ApplicationVO(BaseModel):
    """申请列表项 VO"""
    id: int
    userId: int
    userName: Optional[str] = None
    templateId: int
    templateName: str
    categoryId: Optional[int] = None
    applyScore: float = 0
    gainScore: float = 0
    status: str
    statusText: str
    reviewCount: int = 1
    approvedCount: int = 0
    rejectedCount: int = 0
    reviewerIds: List[int] = Field(default_factory=list)
    attributeInfo: dict = Field(default_factory=dict)        # ★ 新增：attribute 快照
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    proofs: List[ProofVO] = Field(default_factory=list)

    @classmethod
    def from_orm_to_vo(cls, app, with_proofs: bool = False) -> "ApplicationVO":
        """ORM → VO 转换

        Args:
            app: Application ORM 对象
            with_proofs: 是否包含 proofs 详情
        """
        user_name: Optional[str] = None
        if hasattr(app, 'user') and app.user:
            u = app.user
            user_name = getattr(u, 'full_name', None) or getattr(u, 'username', None) or f"user#{app.user_id}"

        vo = cls(
            id=app.id,
            userId=app.user_id,
            userName=user_name,
            templateId=app.template_id,
            templateName=app.template_name,
            categoryId=app.category_id,
            applyScore=float(app.apply_score) if app.apply_score else 0,
            gainScore=float(app.gain_score) if app.gain_score else 0,
            status=app.status,
            statusText=_application_status_text(app.status),
            reviewCount=app.review_count or 1,
            approvedCount=app.approved_count or 0,
            rejectedCount=app.rejected_count or 0,
            reviewerIds=app.reviewer_ids or [],
            attributeInfo=app.attribute_info or {},       # ★ 新增：attribute 快照
            createdAt=app.created_at.isoformat() if app.created_at else None,
            updatedAt=app.updated_at.isoformat() if app.updated_at else None,
        )

        if with_proofs:
            vo.proofs = [ProofVO.from_orm_to_vo(p) for p in (app.proofs or [])]

        return vo


class ApplicationDetailVO(ApplicationVO):
    """申请详情 VO（含操作记录）"""
    operations: List[ApplicationOperationVO] = Field(default_factory=list)

    @classmethod
    def from_orm_to_vo(cls, app, operations: List = None) -> "ApplicationDetailVO":
        """ORM → VO 转换

        Args:
            app: Application ORM 对象
            operations: ApplicationOperation ORM 对象列表
        """
        vo = super().from_orm_to_vo(app, with_proofs=True)
        vo.operations = [ApplicationOperationVO.from_orm_to_vo(op) for op in (operations or [])]
        return vo


class PassResultVO(BaseModel):
    """审核员 PASS 结果 VO"""
    id: int
    status: str
    approvedCount: int
    reviewCount: int
    gainScore: Optional[float] = None

    @classmethod
    def from_orm_to_vo(cls, app) -> "PassResultVO":
        """ORM → VO 转换"""
        return cls(
            id=app.id,
            status=app.status,
            approvedCount=app.approved_count or 0,
            reviewCount=app.review_count or 1,
            gainScore=float(app.gain_score) if app.gain_score else None,
        )


class RejectResultVO(BaseModel):
    """审核员 REJECT 结果 VO"""
    id: int
    status: str
    rejectedCount: int

    @classmethod
    def from_orm_to_vo(cls, app) -> "RejectResultVO":
        """ORM → VO 转换"""
        return cls(
            id=app.id,
            status=app.status,
            rejectedCount=app.rejected_count or 0,
        )


class CancelResultVO(BaseModel):
    """取消申请结果 VO"""
    id: int
    status: str

    @classmethod
    def from_orm_to_vo(cls, app) -> "CancelResultVO":
        """ORM → VO 转换"""
        return cls(
            id=app.id,
            status=app.status,
        )


class ApplicationListVO(Page[ApplicationVO]):
    """申请分页查询结果——即 Page[ApplicationVO]，作为模块级语义别名"""
    pass


__all__ = [
    # Request DTO
    "ProofPayload",
    "ApplicationPayload",
    "ApplicationQueryRequest",
    "PassApplicationRequest",
    "ProofReviewPayload",
    # Response VO
    "ProofVO",
    "ApplicationOperationVO",
    "ApplicationVO",
    "ApplicationDetailVO",
    "PassResultVO",
    "RejectResultVO",
    "CancelResultVO",
    "ApplicationListVO",
]
