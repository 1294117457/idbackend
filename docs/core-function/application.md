# application 实施指南（v4.2）

> **配套文档**：[四层职责设计 § 3 Application（申请记录）](./四层职责设计.md#3-application申请记录)
>
> 本指南给出 application / application_proofs / application_operation 三张表的**实施层面**细节：表结构、状态机、Service 方法签名、Route 形态，以及与现状代码的迁移路径。

---

## 一、职责切分（先于 schema）

| 表 | 职责 | 写操作主体 |
|---|---|---|
| `score_applications` | **核心实体**——一次申请的 apply_score 快照 + 审批状态 | 学生 + 审核员 |
| `application_proofs` | **辅助展示表**——每份证明材料 + 对应分值 + 审核状态 | 学生（增删改 proof） + 审核员（改 proof.status） |
| `application_operation` | **审计日志**——application 层面的事件流（不写 proof 状态变更） | 学生 + 审核员 |

**重要原则**：

- application 是核心，proof 是辅助——proof 不写 audit log，proof.status 自己就是审计介质
- review_proof 不写 application_operation——审核员对 proof 的决定只更新 `application_proofs.status`
- PASSED 时 score_data 流水记录由 `pass_application` 同事务写入，**recalculate 不再同步触发**

---

## 二、schema（最终版）

### 2.1 `score_applications`

```python
"""src/models/application.py"""
from sqlalchemy import String, Integer, ForeignKey, DECIMAL, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
import enum

from .base import Base, TimestampMixin


class ApplicationStatus(str, enum.Enum):
    """application 状态机（v4.2 字符串 6 态）"""
    DRAFT = "DRAFT"
    APPLYING = "APPLYING"
    PASSED = "PASSED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    DISCARDED = "DISCARDED"


class Application(Base, TimestampMixin):
    """加分申请表（核心实体）"""
    __tablename__ = "score_applications"

    # 基础
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    template_id: Mapped[int] = mapped_column(ForeignKey("template.id"))
    template_name: Mapped[str] = mapped_column(String(100))   # 快照，防改名
    category_id: Mapped[int] = mapped_column(ForeignKey("template_category.id"))

    # 分数快照
    apply_score: Mapped[float] = mapped_column(DECIMAL(5, 2))     # 由 calculate 决定的理论分，save_draft 时固化
    gain_score: Mapped[float] = mapped_column(DECIMAL(5, 2), default=0)  # PASSED 时一次性写为 apply_score

    # 状态（v4.2 字符串 6 态）
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

**与现状代码的差异**：

| 现状（src/models/application.py） | v4.2 |
|---|---|
| `status: int` 三态枚举 | `status: str` 六态枚举 |
| `student_id / student_name / major / enrollment_year` | **删除**——从 user 表读 |
| `score_type: int` (硬编码 ACADEMIC/SPECIALTY/ALL) | **删除**——改 `category_id` 外键 |
| `apply_input / proofs_input` | **删除**——前端实时算的 selections 不入库 |
| `current_review_count / reviewer_ids / review_records / remark` | **删除**——下沉到 application_operation |
| `template_id / rule_id` 缺失 | 完整保留 |
| `category_id` 缺失 | 新增 |
| 缺 `gain_score` 数值缓存 | 新增 |

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
        ForeignKey("score_applications.id", ondelete="CASCADE")
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

**与现状代码的差异**：

| 现状 | v4.2 |
|---|---|
| `proof_file_id NOT NULL` | **`file_id` nullable** |
| `proof_value` | 改名为 `proof_score` |
| `review_count / approved_count / status: int / reviewer_ids / review_records / remark` | **全部删除**——审核员对 proof 的决定只更新 `status` 字段 |
| `file` relationship 必填 | **Optional** |

### 2.3 `application_operation`（新建）

```python
class ApplicationOperationType(str, enum.Enum):
    """application 层面的事件类型（v4.2 不含 REVIEW_PROOF）"""
    CREATE_DRAFT = "CREATE_DRAFT"
    UPDATE_DRAFT = "UPDATE_DRAFT"      # 本期不触发，结构保留
    DISCARD_DRAFT = "DISCARD_DRAFT"
    SUBMIT = "SUBMIT"
    PASS = "PASS"
    REJECT = "REJECT"
    RESUBMIT = "RESUBMIT"
    WITHDRAW = "WITHDRAW"
    REVOKE = "REVOKE"                  # 本期不实现，结构保留


class ApplicationOperation(Base, TimestampMixin):
    """申请操作审计日志（application 层）"""
    __tablename__ = "application_operation"

    application_id: Mapped[int] = mapped_column(ForeignKey("score_applications.id"))
    operator_id: Mapped[int] = mapped_column(Integer)
    operator_name: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(
        String(30),
        Enum(ApplicationOperationType, native_enum=False, length=30),
    )
    remark: Mapped[Optional[str]] = mapped_column(Text)

    # **v4.2：没有 target_id / target_type 字段**
    application: Mapped["Application"] = relationship(back_populates="operations")

    __table_args__ = (
        Index("idx_operation_application", "application_id"),
        Index("idx_operation_app_op", "application_id", "operation"),
    )
```

> `created_at` 用 TimestampMixin 自带；operation 表**无** `updated_at`，操作记录不可修改。

---

## 三、状态机（v4.2 终态表）

```
                            ┌─DISCARD──> DISCARDED（终态）
                            │
DRAFT ──SUBMIT──> APPLYING ──REJECT──> REJECTED ──RESUBMIT──> APPLYING
        │              │     │
        │              │     └─ 任一审核员点 REJECT（veto）→ status 立即 REJECTED
        │              │
        │              ├─PASS (approved_count == review_count)──> PASSED（终态）
        │              │
        │              └─WITHDRAW──> WITHDRAWN（终态）
        │
        └─学生继续编辑草稿（允许 0 proof），本期不记 UPDATE_DRAFT
```

| 状态 | 终态？ | 学生操作 | 触发动作 |
|---|---|---|---|
| `DRAFT` | 否 | 任意增删改 proof（**允许 0 proof**） | `SUBMIT` / `DISCARD_DRAFT` |
| `APPLYING` | 否 | 锁定（仅 WITHDRAW 撤回） | 审核员 `PASS` / `REJECT`（veto） |
| `PASSED` | 是 | 锁定 | （REVOKE 未来扩展） |
| `REJECTED` | 否 | 任意增删改 proof | `RESUBMIT` → APPLYING |
| `WITHDRAWN` | 是 | 锁定 | — |
| `DISCARDED` | 是 | 锁定 | — |

### 3.1 `review_count` 的两种业务场景

`review_count` 字段控制 application 通过所需的不同审核员数：

**场景 A：`review_count = 1`（单人审核，单步通过）**

```
[1] 学生提交 → APPLYING
[2] 审核员 A：审完全部 proof（全部 APPROVED）→ 投 PASS application
        └─ approved_count = 1 == review_count → PASSED
        └─ 同事务：gain_score = apply_score + 写 score_data
        └─ application 终态
```

如果发现 application 有问题，必须走 REVOKE 撤销流程（v4.2 仅结构预留）。

**场景 B：`review_count ≥ 2`（多人会签 + 一票否决）**

```
[1] 学生提交 → APPLYING

[2] 审核员 A：审 proof 1 (PENDING → APPROVED)
[3] 审核员 A：审 proof 2 (PENDING → APPROVED)
[4] 审核员 A：投 PASS application → approved_count = 1, status 仍为 APPLYING

[5] 审核员 B：审 proof 1 (APPROVED → REJECTED)  ← B 覆盖 A 的决定
        └─ proof 1 不再算 APPROVED
        └─ service 不主动触发 application 状态变化

[6] 审核员 B：试图投 PASS application
        └─ service 校验：COUNT(proof.status IN ('PENDING','REJECTED')) == 0
        └─ 失败：proof 1 是 REJECTED → 409 Conflict
        └─ 前端提示"还有 1 份证明未通过"

[7] 审核员 B：改投 REJECT application（veto）
        └─ application.status = REJECTED
        └─ A 的 PASS 操作记录保留在 application_operation 历史中
        └─ proof 状态保留（A 的 APPROVED 被 B 改成 REJECTED）
```

**关键不变量**：

1. **proof.status 是会签中间状态**——任意审核员都可以修改（包括覆盖前审核员的决定）
2. **proof 不需要 review_count / approved_count 字段**——proof 的"是否通过"由最后一个改它的审核员决定
3. **proof.status 改变不会自动触发 application.status 变化**——审核员改完 proof 后必须主动投 application
4. **PASSED 是 proof 和 application 的双重终态**——PASSED 之后 review_proof 返回 409
5. **gain_score 是 application 整体通过的快照**——proof.status 变化不影响 gain_score

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
      1. 业务级唯一校验:
         SELECT * FROM score_applications
          WHERE user_id=? AND template_id=? AND status IN ('DRAFT','APPLYING','PASSED')
         - 命中 DRAFT → 继续（覆盖更新）
         - 命中 APPLYING / PASSED → 抛 ConflictError
         - 命中 0 → 新建 application（DRAFT）
      2. 计算 apply_score:
         template = TemplateService.get_with_rules(db, template_id)
         apply_score = ScoreCalculationService.calculate(template, user_selections)
      3. CREATE 或 UPDATE application:
         - 快照 template_name / review_count / category_id
         - status='DRAFT'，apply_score=计算结果
      4. 整体替换 proof 集合:
         DELETE FROM application_proofs WHERE application_id = ?
         INSERT proof_data_list（status=PENDING，file_id nullable）
      5. 返回 application（含 proofs）

    不写 application_operation（草稿操作噪声大）
    """
```

### 4.2 `discard_draft(db, application_id, user_id, remark?) -> Application`

```python
async def discard_draft(db, application_id, user_id, remark=None) -> Application:
    """
    流程:
      1. SELECT application FOR UPDATE
      2. 校验 user_id == current_user.id（仅本人）
      3. 校验 status == 'DRAFT'（APPLYING 应走 WITHDRAW）
      4. UPDATE status='DISCARDED'
      5. INSERT application_operation(DISCARD_DRAFT, operator_id, operator_name, remark)
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
      7. INSERT application_operation(SUBMIT)
      8. 提交事务
    """
```

### 4.4 `withdraw(db, application_id, user_id, remark?) -> Application`

```python
async def withdraw(db, application_id, user_id, remark=None) -> Application:
    """
    流程:
      1. SELECT application FOR UPDATE
      2. 校验 user_id == current_user.id
      3. 校验 status == 'APPLYING'
      4. UPDATE status='WITHDRAWN'
      5. INSERT application_operation(WITHDRAW, remark=optional)
      6. 提交事务
    proof 不动（保留审计）
    """
```

### 4.5 `review_proof(db, proof_id, reviewer_id, action, remark?) -> ApplicationProof`

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
      3. **v4.2 校验**：当前 reviewer_id 没有审过这条 proof（同审核员不能重复表达决定）
         注：不同审核员可以互相覆盖——B 可以把 A 的 APPROVED 改成 REJECTED（veto 视角）
      4. UPDATE proof SET status = ?  ← 不带 AND status='PENDING' 条件，允许覆盖
      5. 提交事务
      6. 返回更新后的 proof

    **不写 application_operation**（proof 状态变更只反映在 proof.status）
    **不更新 application.gain_score**（v4.2 决策——gain_score 在 PASSED 时一次性写）
    **不强制要求 remark**（v4.2 放宽）

    **业务语义**：proof.status 是会签中间状态，任意审核员都可修改。
                 proof 不需要 review_count / approved_count 字段。
    """
```

### 4.6 `pass_application(db, application_id, reviewer_id, reviewer_name, remark?) -> Application`

```python
async def pass_application(
    db, application_id, reviewer_id, reviewer_name,
    remark: Optional[str] = None,
) -> Application:
    """
    流程:
      1. SELECT application FOR UPDATE
      2. SELECT 是否存在 operation(PASS|REJECT, operator_id=reviewer_id) — 拒绝已投过票的
      3. 校验 application.status == 'APPLYING'
      4. **v4.2 校验**：该 application 下所有 proof.status == 'APPROVED'
         （即 COUNT(proof.status IN ('PENDING','REJECTED')) == 0）
         如果有 proof 是 PENDING 或 REJECTED，B 投 PASS 必然失败（service 返回 409）
      5. UPDATE approved_count = approved_count + 1（CAS 单 SQL）
      6. 若 approved_count == review_count:
         a. UPDATE application SET status='PASSED', gain_score=apply_score
         b. ScoreDataService.record(... apply_score ...)
      7. INSERT application_operation(PASS, operator_id, operator_name, remark)
      8. 提交事务

    **本期不触发 recalculate**（解耦到独立接口）

    **业务场景**：
      - review_count=1：单人审核，A 审完所有 proof + 投 PASS → 立即 PASSED
      - review_count≥2：多人会签，必须 N 个不同审核员都投 PASS 才 PASSED
        如果中途有 B 把某条 proof 改成 REJECTED → B 投 PASS 必然失败 → B 改投 REJECTED（veto）
    """
```

### 4.7 `reject_application(db, application_id, reviewer_id, reviewer_name, remark: str) -> Application`

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
      6. INSERT application_operation(REJECT, operator_id, operator_name, remark)
      7. 提交事务
    """
```

### 4.8 `resubmit(db, application_id, user_id, proof_data_list) -> Application`

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
      8. UPDATE application.status='APPLYING'
         - approved_count / rejected_count **不重置**（保留历史投票）
      9. INSERT application_operation(RESUBMIT)
      10. 提交事务
    """
```

---

## 五、Service 方法签名（ApplicationOperationService）

`ApplicationOperationService` 位置：`src/services/application_operation_service.py`

```python
async def list_by_application(db, application_id) -> list[ApplicationOperation]:
    """返回 application 全部操作历史，按 created_at ASC"""

async def list_votes(db, application_id) -> list[ApplicationOperation]:
    """仅返回 operation IN ('PASS','REJECT') 的投票记录，详情页用"""

async def has_voted(db, application_id, operator_id) -> bool:
    """判断 (application_id, operator_id) 是否已投过票（任一 PASS/REJECT）"""
```

---

## 六、Route 接口（RESTful 设计）

`src/app/routes/application.py`

| Method & Path | Service 调用 | 角色 | 说明 |
|---|---|---|---|
| `POST   /api/applications/draft` | `save_draft` | 学生 | 创建 / 覆盖草稿 |
| `DELETE /api/applications/draft/{id}` | `discard_draft` | 学生 | 删除草稿 |
| `POST   /api/applications/{id}/submit` | `submit` | 学生 | DRAFT → APPLYING |
| `POST   /api/applications/{id}/withdraw` | `withdraw` | 学生 | APPLYING → WITHDRAWN |
| `POST   /api/applications/{id}/resubmit` | `resubmit` | 学生 | REJECTED → APPLYING |
| `POST   /api/applications/{id}/proofs/{proof_id}/review` | `review_proof` | 审核员 | 改 proof.status |
| `POST   /api/applications/{id}/pass` | `pass_application` | 审核员 | 投 PASS 票，达 N → PASSED |
| `POST   /api/applications/{id}/reject` | `reject_application` | 审核员 | veto |
| `GET    /api/applications/{id}` | GET service | 学生 / 审核员 | 详情（含 proofs + operations） |
| `GET    /api/applications` | LIST service | 学生 | 我的申请列表 |
| `GET    /api/admin/applications` | LIST service | 审核员 | 待审核列表（status=APPLYING） |

**request body 示例**（`POST /api/applications/draft`）：

```json
{
  "template_id": 1,
  "user_selections": {
    "rule_1": "attribute_3",
    "rule_2": "75.0"
  },
  "proof_data_list": [
    { "file_id": 100, "proof_score": 3.0 },
    { "file_id": null, "proof_score": 1.5 }
  ]
}
```

**response 示例**（`POST /api/applications/draft`）：

```json
{
  "id": 123,
  "user_id": 456,
  "template_id": 1,
  "template_name": "竞赛奖项",
  "category_id": 5,
  "apply_score": 4.5,
  "gain_score": 0,
  "status": "DRAFT",
  "review_count": 2,
  "approved_count": 0,
  "rejected_count": 0,
  "proofs": [
    { "id": 1, "file_id": 100, "proof_score": 3.0, "status": "PENDING" },
    { "id": 2, "file_id": null, "proof_score": 1.5, "status": "PENDING" }
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

---

## 七、与现状代码的迁移步骤

### 7.1 Migration 顺序（强依赖）

```
Step 1: User 表
  ALTER TABLE users ADD COLUMN score_info JSONB DEFAULT '{}';
  ALTER TABLE users ADD COLUMN extra_info JSONB DEFAULT '{}';

Step 2: Application 表迁移（核心）
  -- 改 status 字段类型
  ALTER TABLE score_applications ALTER COLUMN status TYPE VARCHAR(20) USING
    CASE status
      WHEN 0 THEN 'APPLYING'  -- 历史 PENDING
      WHEN 1 THEN 'PASSED'
      WHEN 2 THEN 'REJECTED'
    END;
  -- 删字段（先确保应用层不再用）
  ALTER TABLE score_applications
    DROP COLUMN IF EXISTS student_id,
    DROP COLUMN IF EXISTS student_name,
    DROP COLUMN IF EXISTS major,
    DROP COLUMN IF EXISTS enrollment_year,
    DROP COLUMN IF EXISTS score_type,
    DROP COLUMN IF EXISTS apply_input,
    DROP COLUMN IF EXISTS proofs_input,
    DROP COLUMN IF EXISTS current_review_count,
    DROP COLUMN IF EXISTS reviewer_ids,
    DROP COLUMN IF EXISTS review_records,
    DROP COLUMN IF EXISTS remark;
  -- 加字段
  ALTER TABLE score_applications
    ADD COLUMN template_id INTEGER NOT NULL REFERENCES template(id),
    ADD COLUMN category_id INTEGER REFERENCES template_category(id),  -- 第一阶段允许 NULL（迁移期）
    ALTER COLUMN apply_score TYPE DECIMAL(5,2),
    ALTER COLUMN gain_score TYPE DECIMAL(5,2),
    ADD COLUMN rejected_count INTEGER DEFAULT 0;
  UPDATE score_applications SET template_id = 1 WHERE template_id IS NULL;  -- 迁移占位
  ALTER TABLE score_applications ALTER COLUMN template_id SET NOT NULL;
  ALTER TABLE score_applications ALTER COLUMN category_id SET NOT NULL;

Step 3: ApplicationProof 表
  -- proof_value → proof_score
  ALTER TABLE application_proofs RENAME COLUMN proof_value TO proof_score;
  ALTER TABLE application_proofs ALTER COLUMN proof_score TYPE DECIMAL(5,2);
  ALTER TABLE application_proofs RENAME COLUMN proof_file_id TO file_id;
  ALTER TABLE application_proofs ALTER COLUMN file_id DROP NOT NULL;
  -- 删字段
  ALTER TABLE application_proofs
    DROP COLUMN IF EXISTS review_count,
    DROP COLUMN IF EXISTS approved_count,
    DROP COLUMN IF EXISTS status_old,  -- 旧 status: int
    ALTER COLUMN status TYPE VARCHAR(20) USING
      CASE status
        WHEN 0 THEN 'PENDING'
        WHEN 1 THEN 'APPROVED'
        WHEN 2 THEN 'REJECTED'
      END,
    DROP COLUMN IF EXISTS reviewer_ids,
    DROP COLUMN IF EXISTS review_records,
    DROP COLUMN IF EXISTS remark;

Step 4: 新建 application_operation
  CREATE TABLE application_operation (
      id              SERIAL PRIMARY KEY,
      application_id  INTEGER NOT NULL REFERENCES score_applications(id),
      operator_id     INTEGER NOT NULL,
      operator_name   VARCHAR(100) NOT NULL,
      operation       VARCHAR(30) NOT NULL
                      CHECK (operation IN ('CREATE_DRAFT','UPDATE_DRAFT','DISCARD_DRAFT',
                                            'SUBMIT','PASS','REJECT','RESUBMIT','WITHDRAW','REVOKE')),
      remark          TEXT,
      created_at      TIMESTAMP DEFAULT NOW(),
      updated_at      TIMESTAMP DEFAULT NOW()  -- TimestampMixin 模板要求
  );
  CREATE INDEX idx_operation_application ON application_operation(application_id);
  CREATE INDEX idx_operation_app_op      ON application_operation(application_id, operation);
```

### 7.2 模型类对应改造

| src/models/application.py | v4.2 |
|---|---|
| `class ApplicationStatus(int, enum.Enum)` | 改为 `class ApplicationStatus(str, enum.Enum)` 6 态 |
| `class Application` | 删 5 个字段、改 status 类型、加 category_id / rejected_count、改 FK 类型 |
| `class ApplicationProof` | 改 4 字段名 / 类型，删 5 字段 |
| 新增 | `class ApplicationProof.status: str Enum + ApplicationOperation` 两个新模型 |

> **文件归属建议**：把 `ApplicationOperation` 拆到独立文件 `src/models/application_operation.py`，与现状 application.py 解耦。

### 7.3 应用层代码改造

| src/services/application_service.py | v4.2 |
|---|---|
| `ApplicationStatus(int enum)` 引用 | 全部替换为新 6 态 |
| `create_application` | 重命名为 `save_draft`，加业务级唯一约束校验 |
| `add_proof / remove_proof` | 删除——submit / resubmit 改为整体替换 |
| `submit_application` | 重写为 `submit`：强校验 ≥ 1 proof + sum 守恒 |
| 无 | 新增 `discard_draft` / `withdraw` / `resubmit` / `pass_application` / `reject_application` |
| 无 | 新增 `review_proof`（不写 operation） |
| `approve_application` / `reject_application` | 重写为新 `pass_application`（加审核员去重 + 全部 proof 已审完校验） / `reject_application`（加 remark 必填） |
| `cancel_application` 物理 DELETE | 删除——改为软终态 WITHDRAWN / DISCARDED |
| 无 | 新增 `src/services/application_operation_service.py` |

### 7.4 路由改造

| src/app/routes/application.py | v4.2 |
|---|---|
| 8 个旧 endpoint | 重构成上表 11 个 endpoint |
| `route/submitBonusApplication` 一次提交 | 拆为 `save_draft` + `submit` 两个 endpoint |
| `route/approveBonusApplication` | 改为 `POST /api/applications/{id}/pass` |
| 无 | 新增 `/review`、`/withdraw`、`/discard_draft`、`/resubmit` |
| 缺 operation 查询 | 新增 `list_by_application` / `list_votes` 走 operation 服务 |

---

## 八、未决项与已知妥协

| 项 | 当前决策 | 替代方案 |
|---|---|---|
| CREATE_DRAFT 日志 | 本期不写（结构保留） | 按内容 hash 去重后写 |
| UPDATE_DRAFT 日志 | 本期不写（结构保留） | 每次 save_draft 写一条 + content_hash |
| WITHDRAWN 是否能回到 DRAFT 编辑 | 否（WITHDRAWN 是终态） | 加 WITHDRAW_UNDO 操作类型 |
| RESUBMIT 是否重置 approved_count / rejected_count | 否（保留历史投票） | 是（重新会签） |
| 同一审核员能否取消自己的投票 | 否（一旦投不能撤回） | 加 CANCEL_VOTE 操作类型 |
| proof 能否完全跨状态自由操作 | **是**（任意审核员可覆盖前审核员的 status） | 锁定 APPROVED proof（防 veto） |
| recalculate 触发时机 | 学生 / 管理员手动触发 | MQ 异步 / 同事务同步 |
| PASSED 之后能否再 review_proof | **否**（PASSED 是双重终态） | 允许（仅记录不触发 application.status 变化） |
| proof 状态修改记录是否要写 operation | **否**（proof.status 是事实来源） | 是（用 REVIEW_PROOF + reviewer_id 追踪每条 proof 的"谁审过"） |
| review_count = 0 的合法性 | 拒绝（必须 ≥ 1） | 允许（无需审核，直接 PASSED） |

---

## 九、相关文件清单

```
src/
  models/
    application.py                  # Application（重构）+ ApplicationProof（简化）
    application_operation.py        # ApplicationOperation（新建，单独文件）
  services/
    application_service.py          # 8 个方法（save_draft / discard_draft / submit / withdraw /
                                    #       review_proof / pass_application / reject_application / resubmit）
    application_operation_service.py  # list_by_application / list_votes / has_voted
  app/routes/
    application.py                  # 11 个 endpoint
```

实施时**严格按本指南落地**；如有新需求先回本指南增改章节再写代码。
