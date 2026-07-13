"""申请模块 DTO / VO（v4.5）

═══════════════════════════════════════════════════════════════════════
设计要点
═══════════════════════════════════════════════════════════════════════
三个写接口（saveDraft / submit / edit-submit）共享同一组 Payload：
  - ApplicationPayload：application 主体 + proofs 整表替换列表
  - ProofPayload       ：单条 proof（proofId 决定新建/更新；fileId 决定是否重传）

applicationId 决定"新建 vs 更新"：
  - saveDraft          ：可为 None（新建 DRAFT）或 非空（仅 DRAFT 可更新）
  - submit             ：必须 None（新建 APPLYING）
  - edit-submit        ：必须 非空（仅 DRAFT/REJECTED/REVOKED 可编辑并提交）
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict


# ═══════════════════════════════════════════════════════════════════════
# Request DTO
# ═══════════════════════════════════════════════════════════════════════

class ProofPayload(BaseModel):
    """单条 proof（前台编辑后提交）。

    字段语义：
      - proofId 为 None  → 新建
      - proofId 非空      → 更新；id 对应的旧 proof 必须属于本 application
      - fileId 为 None    → 该 proof 本轮没上传文件（仅在新建/重置为待补充时允许）
      - fileId 非空且与旧值不同 → 重置 status=PENDING
      - proofScore < 0   → 字段校验失败（Pydantic 报错）
    """
    model_config = ConfigDict(populate_by_name=True)

    proofId: Optional[int] = Field(default=None)
    fileId: Optional[int] = Field(default=None)
    proofScore: float = Field(ge=0, description="证明分；新建时可临时为 0")


class ApplicationPayload(BaseModel):
    """统一申请 Payload（saveDraft / submit / edit-submit 三接口共用）。

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


__all__ = [
    "ProofPayload",
    "ApplicationPayload",
]
