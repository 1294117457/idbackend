# application 实施指南（v4.3）

> **配套文档**：[四层职责设计 § 3 Application（申请记录）](./四层职责设计.md#3-application申请记录)
>
> 本指南给出 application / application_proofs / application_operation 三张表的**实施层面**细节：表结构、状态机、Service 方法签名、Route 形态，以及与现状代码的迁移路径。

---

## 一、职责切分（先于 schema）

| 表 | 职责 | 写操作主体 |
|---|---|---|
| `applications` | **核心实体**——一次申请的 apply_score 快照 + 审批状态 | 学生 + 审核员 |
| `application_proofs` | **辅助展示表**——每份证明材料 + 对应分值 + 审核状态 | 学生（增删改 proof） + 审核员（改 proof.status） |
| `application_operation` | **审计日志**——application 层面的事件流（不写 proof 状态变更） | 学生 + 审核员 |

**重要原则**：

- application 是核心，proof 是辅助——proof 不写 audit log，proof.status 自己就是审计介质
- review_proof 不写 application_operation——审核员对 proof 的决定只更新 `application_proofs.status`
- PASSED 时 score_data 流水记录由 `pass_application` 同事务写入，**recalculate 不再同步触发**

---

## 二、schema（v4.3 最终版）

### 2.1 `applications`

```python
"""src/models/application.py"""
from sqlalchemy import String, Integer, ForeignKey, DECIMAL, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
import enum

from .base import Base, TimestampMixin


class ApplicationStatus(str, enum.Enum):
    """application 状态机（v4.3 字符串 5 态）"""
    DRAFT = "DRAFT"          # 草稿（学生可编辑）
    APPLYING = "APPLYING"   # 审核中（学生锁定）
    PASSED = "PASSED"       # 通过（终态）
    REJECTED = "REJECTED"   # 拒绝（可重提，老师操作）
    CANCELLED = "CANCELLED" # 已取消（终态，学生主动取消）
    REVOKED = "REVOKED"     # 已撤回（终态，老师撤回通过的申请）


class Application(Base, TimestampMixin):
    """加分申请表（核心实体）"""
    __tablename__ = "applications"

    # 基础
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    template_id: Mapped[int] = mapped_column(ForeignKey("template.id"))
    template_name: Mapped[str] = mapped_column(String(100))   # 快照，防改名
    category_id: Mapped[int] = mapped_column(ForeignKey("template_category.id"))

    # 分数快照
    apply_score: Mapped[float] = mapped_column(DECIMAL(5, 2))     # 由 calculate 决定的理论分，save_draft 时固化
    gain_score: Mapped[float] = mapped_column(DECIMAL(5, 2), default=0)  # PASSED 时一次性写为 apply_score

    # 状态（v4.3 字符串 5 态）
    status: Mapped[str] = mapped_column(
        String(20),
        Enum(ApplicationStatus, native_enum=False, length=20),
        default=ApplicationStatus.DRAFT.value,
    )

    # 审核员投票
    review_count: Mapped[int] = mapped_column(Integer, default=1)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)

    # 关系
    user: Mapped["User"] = relationship(back_populates="applications")
    proofs: Mapped[List["ApplicationProof"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    operations: Mapped[List["ApplicationOperation"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_application_user_template_status", "user_id", "template_id", "status"),
        Index("idx_application_status", "status"),
    )
```

### 2.2 `application_proofs`

```python
class ProofStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApplicationProof(Base, TimestampMixin):
    """申请证明材料（辅助展示表）"""
    __tablename__ = "application_proofs"

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("file_metadata.id"), nullable=True   # v4.2 改为可空，允许文字描述
    )
    proof_score: Mapped[float] = mapped_column(DECIMAL(5, 2))
    status: Mapped[str] = mapped_column(
        String(20),
        Enum(ProofStatus, native_enum=False, length=20),
        default=ProofStatus.PENDING.value,
    )

    application: Mapped["Application"] = relationship(back_populates="proofs")
    file: Mapped[Optional["FileMetadata"]] = relationship("FileMetadata")

    __table_args__ = (
        Index("idx_proofs_application", "application_id"),
        Index("idx_proofs_application_status", "application_id", "status"),
    )
```

### 2.3 `application_operation`（v4.3 简化版）

```python
class ApplicationOperation(Base, TimestampMixin):
    """申请操作审计日志（application 层）

    v4.3 关键决策：
      - operation 字段改为存储操作后的 application.status
      - 没有 operator_type 字段（谁操作由业务逻辑隐含）
      - 没有 target_id / target_type 字段
      - 草稿修改（save_draft）本期不写——噪音大
    """
    __tablename__ = "application_operation"

    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    operator_id: Mapped[int] = mapped_column(Integer)
    operator_name: Mapped[str] = mapped_column(String(100))
    # 操作后 application 的状态
    status: Mapped[str] = mapped_column(
        String(20),
        Enum(ApplicationStatus, native_enum=False, length=20),
    )
    remark: Mapped[Optional[str]] = mapped_column(Text)

    application: Mapped["Application"] = relationship(back_populates="operations")

    __table_args__ = (
        Index("idx_operation_application", "application_id"),
        Index("idx_operation_app_status", "application_id", "status"),
    )
```

> `created_at` 用 TimestampMixin 自带；operation 表**无** `updated_at`，操作记录不可修改。

---

## 三、状态机（v4.3 终态表）

```
                            ┌─学生取消──> CANCELLED（终态）
                            │
DRAFT ──提交──> APPLYING ──老师拒绝──> REJECTED ──学生重提──> APPLYING
        │              │     │
        │              │     └─ 老师拒绝（veto）→ status 立即 REJECTED
        │              │
        │              ├─老师通过 (approved_count == review_count)──> PASSED（终态）
        │              │
        │              └─学生取消──> CANCELLED（终态）
        │
        └─学生取消──> CANCELLED（终态）
        
                                   
老师撤回通过: PASSED ──老师撤回──> REVOKED（终态）
```

### 3.1 状态语义

| 状态 | 终态？ | 学生操作 | 老师操作 |
|---|---|---|---|
| `DRAFT` | 否 | 编辑/提交/取消 | - |
| `APPLYING` | 否 | 取消 | 通过/拒绝 |
| `PASSED` | 是 | - | 撤回 |
| `REJECTED` | 否 | 修改proof/重提 | - |
| `CANCELLED` | 是 | - | - |
| `REVOKED` | 是 | - | - |

### 3.2 操作与状态映射（v4.3）

| 操作 | 触发者 | 状态变化 | operation.status 值 |
|---|---|---|---|
| 创建草稿 | 学生 | → DRAFT | `DRAFT` |
| 取消草稿 | 学生 | DRAFT → CANCELLED | `CANCELLED` |
| 提交申请 | 学生 | DRAFT → APPLYING | `APPLYING` |
| 取消申请 | 学生 | APPLYING → CANCELLED | `CANCELLED` |
| 重提申请 | 学生 | REJECTED → APPLYING | `APPLYING` |
| 通过申请 | 老师 | APPLYING → PASSED | `PASSED` |
| 拒绝申请 | 老师 | APPLYING → REJECTED | `REJECTED` |
| 撤回申请 | 老师 | PASSED → REVOKED | `REVOKED` |

---

## 四、Service 方法签名（直接对应 Layer 3 文档）

`ApplicationService` 位置：`src/services/application_service.py`

### 4.1 `save_draft(db, user_id, template_id, user_selections, proof_data_list) -> Application`

```python
async def save_draft(
    db: AsyncSession,
    user_id: int,
    template_id: int,
    user_selections: dict,         # { rule_id: attribute_id 或 input_str }
    proof_data_list: list[dict],   # [{file_id?, proof_score}, ...]
) -> Application:
    """
    流程:
      1. 业务级活申请校验:
         SELECT * FROM applications
          WHERE user_id=? AND template_id=? AND status IN ('APPLYING','PASSED')
         - 命中 APPLYING → 抛 ConflictError（申请审核中，无法新建草稿）
         - 命中 PASSED  → 抛 ConflictError（已通过，无法重复申请）
         - 未命中 → 新建 application（DRAFT）
      2. 计算 apply_score:
         template = TemplateService.get_with_rules(db, template_id)
         apply_score = ScoreCalculationService.calculate(template, user_selections)
      3. CREATE application（DRAFT）:
         - 快照 template_name / review_count（从 template 读，**不接受客户端传入**）/ category_id
         - status='DRAFT'，apply_score=计算结果，gain_score=0
      4. 整体替换 proof 集合:
         INSERT proof_data_list（status=PENDING，file_id nullable）
      5. 返回 application（含 proofs）
    """
```

### 4.2 `cancel(db, application_id, user_id, remark?) -> Application`

```python
async def cancel(db, application_id, user_id, remark=None) -> Application:
    """
    学生主动取消申请（终态）:
    
    状态变化:
      - DRAFT → CANCELLED
      - APPLYING → CANCELLED
    
    流程:
      1. SELECT application FOR UPDATE
      2. 校验 user_id == current_user.id（仅本人）
      3. 校验 status IN ('DRAFT', 'APPLYING')
      4. UPDATE status='CANCELLED'
      5. INSERT application_operation(status='CANCELLED', remark=optional)
      6. 提交事务
    """
```

### 4.3 `submit(db, application_id, user_id) -> Application`

```python
async def submit(db, application_id, user_id) -> Application:
    """
    流程:
      1. SELECT application FOR UPDATE
      2. 校验 user_id == current_user.id
      3. 校验 status == 'DRAFT'  ← 仅 DRAFT 可 submit
      4. 加载现有 proofs，校验:
         - len(proofs) >= 1   ← 草稿允许 0，submit 必须 ≥ 1
         - sum(p.proof_score for p in proofs) == apply_score  ← DECIMAL 精度对齐
         任意失败抛 400
      5. 整体替换 proof 集合（重新 INSERT，status=PENDING）
      6. UPDATE application.status='APPLYING'
      7. INSERT application_operation(status='APPLYING')
      8. 提交事务
    """
```

### 4.4 `review_proof(db, proof_id, reviewer_id, action, remark?) -> ApplicationProof`

```python
async def review_proof(
    db, proof_id, reviewer_id, reviewer_name,
    action: Literal["APPROVED", "REJECTED"],
    remark: Optional[str] = None,
) -> ApplicationProof:
    """
    流程:
      1. SELECT proof JOIN application FOR UPDATE
      2. 校验 application.status == 'APPLYING'  ← PASSED 之后 proof 不能再改
      3. UPDATE proof SET status = action
      4. 提交事务，返回更新后的 proof
    """
```

### 4.5 `pass_application(db, application_id, reviewer_id, reviewer_name, remark?) -> Application`

```python
async def pass_application(
    db, application_id, reviewer_id, reviewer_name,
    remark: Optional[str] = None,
) -> Application:
    """
    流程:
      1. SELECT application FOR UPDATE
      2. SELECT 是否存在 operation(operator_id=reviewer_id) — 拒绝已投过票的
      3. 校验 application.status == 'APPLYING'
      4. 校验：该 application 下所有 proof.status == 'APPROVED'
      5. UPDATE approved_count = approved_count + 1（CAS 单 SQL）
      6. 若 approved_count == review_count:
         a. UPDATE application SET status='PASSED'
         b. ScoreDataService.record(... application.gain_score ...)
      7. INSERT application_operation(status='PASSED', operator_id, operator_name, remark)
      8. 提交事务
    """
```

### 4.6 `reject_application(db, application_id, reviewer_id, reviewer_name, remark: str) -> Application`

```python
async def reject_application(
    db, application_id, reviewer_id, reviewer_name,
    remark: str,    # **必填**
) -> Application:
    """
    流程:
      1. SELECT application FOR UPDATE
      2. 校验 application.status == 'APPLYING'
      3. 校验 remark.strip() 非空
      4. 校验 (reviewer_id, application_id) 未在 operation 上投过票
      5. UPDATE application SET status='REJECTED', rejected_count+=1
      6. INSERT application_operation(status='REJECTED', operator_id, operator_name, remark)
      7. 提交事务
    """
```

### 4.7 `resubmit(db, application_id, user_id, proof_data_list) -> Application`

```python
async def resubmit(
    db, application_id, user_id, proof_data_list: list[dict],
) -> Application:
    """
    **与 submit 完全同构**——不接收 delete_proof_ids / new_proof_data_list，
    统一走"整体替换 proof 列表 + sum 校验"。

    流程:
      1. SELECT application FOR UPDATE
      2. 校验 user_id == current_user.id
      3. 校验 status == 'REJECTED'
      4. 校验 len(proof_data_list) >= 1
      5. 校验 sum(p.proof_score for p in proof_data_list) == apply_score
      6. DELETE FROM application_proofs WHERE application_id = ?
      7. INSERT proof_data_list（status=PENDING）
      8. UPDATE application.status='APPLYING', gain_score=0  ← **重置**
      9. INSERT application_operation(status='APPLYING')
      10. 提交事务
    """
```

### 4.8 `revoke_application(db, application_id, reviewer_id, reviewer_name, remark: str) -> Application`

```python
async def revoke_application(
    db, application_id, reviewer_id, reviewer_name,
    remark: str,    # **必填**
) -> Application:
    """
    老师撤回已通过的申请（终态）:

    流程:
      1. SELECT application FOR UPDATE
      2. 校验 application.status == 'PASSED'
      3. 校验 remark 非空
      4. UPDATE application SET status='REVOKED'
      5. INSERT application_operation(status='REVOKED', operator_id, operator_name, remark)
      6. 提交事务
    """
```

---

## 五、Service 方法签名（ApplicationOperationService）

`ApplicationOperationService` 位置：`src/services/application_operation_service.py`

```python
async def list_by_application(db, application_id) -> list[ApplicationOperation]:
    """返回 application 全部操作历史，按 created_at ASC"""

async def list_votes(db, application_id) -> list[ApplicationOperation]:
    """返回所有投票记录（status IN ('PASSED','REJECTED')），详情页用"""

async def has_voted(db, application_id, operator_id) -> bool:
    """判断 (application_id, operator_id) 是否已投过票"""
```

---

## 六、Route 接口（RESTful 设计）

`src/app/routes/application.py`

| Method & Path | Service 调用 | 角色 | 说明 |
|---|---|---|---|
| `POST   /api/applications/draft` | `save_draft` | 学生 | 创建 / 覆盖草稿 |
| `POST   /api/applications/{id}/cancel` | `cancel` | 学生 | 取消申请（DRAFT/APPLYING → CANCELLED） |
| `POST   /api/applications/{id}/submit` | `submit` | 学生 | DRAFT → APPLYING |
| `POST   /api/applications/{id}/resubmit` | `resubmit` | 学生 | REJECTED → APPLYING |
| `POST   /api/applications/{id}/proofs/{proof_id}/review` | `review_proof` | 审核员 | 改 proof.status |
| `POST   /api/applications/{id}/pass` | `pass_application` | 审核员 | 投 PASS 票，达 N → PASSED |
| `POST   /api/applications/{id}/reject` | `reject_application` | 审核员 | veto |
| `POST   /api/applications/{id}/revoke` | `revoke_application` | 审核员 | 撤回已通过的申请 |
| `GET    /api/applications/{id}` | GET service | 学生 / 审核员 | 详情（含 proofs + operations） |
| `GET    /api/applications` | LIST service | 学生 | 我的申请列表 |
| `GET    /api/admin/applications` | LIST service | 审核员 | 待审核列表（status=APPLYING） |

---

## 七、与现状代码的迁移步骤

### 7.1 Migration 顺序

```
Step 1: 更新 applications.status CHECK 约束
  - 移除 WITHDRAWN/DISCARDED，添加 CANCELLED/REVOKED

Step 2: 数据迁移
  - UPDATE applications SET status = 'CANCELLED' WHERE status IN ('WITHDRAWN', 'DISCARDED')

Step 3: 更新 application_operation
  - operation 字段映射为 status（DRAFT/APPLYING/PASSED/REJECTED/CANCELLED/REVOKED）
  - operation → status
  - idx_operation_app_op → idx_operation_app_status
```

详见迁移文件：`migrations/016_application_v43.py`

---

## 八、未决项与已知妥协

| 项 | 当前决策 | 替代方案 |
|---|---|---|
| CANCELLED 后能否重新申请 | 可以（创建新草稿） | - |
| REVOKED 后能否重新申请 | 可以（创建新草稿） | - |
| REJECTED 重提 | 可以，但只修改 proof，不修改 apply_score | 新建申请可修改分数 |
| PASSED 后能否撤回 | 可以，通过 REVOKED（老师操作） | - |

---

## 九、相关文件清单

```
src/
  models/
    application.py                  # Application + ApplicationProof + ApplicationOperation
  services/
    application_service.py          # 8 个方法
    application_operation_service.py  # list_by_application / list_votes / has_voted
  app/routes/
    application.py                  # 11 个 endpoint
```

实施时**严格按本指南落地**；如有新需求先回本指南增改章节再写代码。
