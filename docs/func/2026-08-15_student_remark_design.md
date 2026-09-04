# 学生备注字段功能设计文档（学生端申请备注）

> 目的：在 `applications` 表中新增"学生备注"字段，并在学生端申请弹窗（`TemplateApplyDialog.vue`）中提供输入框；学生可在填写申请时录入一段说明性文本，随申请一起提交、保存草稿、编辑重提，供审核员审阅。
>
> 本文为设计文档，**不包含实际代码改动**，仅给出改动点、改动内容和决策依据，等待确认后再实施。

---

## 一、需求复述

| 项目 | 内容 |
|---|---|
| 字段名（业务） | 学生备注 |
| 输入位置 | `idfrontend/src/views/template/components/TemplateApplyDialog.vue`（Step 2 证明材料下方，或 Step 1 底部） |
| 用途 | 学生提交申请时附带的一段说明，例如"家庭特殊情况说明""成绩排名补充说明"等，供审核员参考 |
| 写入时机 | 保存草稿（save）、新建提交（submit）、编辑重提（edit） |
| 读取对象 | 学生本人（详情回显）、审核员（审核时查看） |
| 是否必填 | 否（选填） |
| 长度上限 | 建议 500 字符（前端限制 + 后端校验） |
| 是否走审核日志 | 否（区别于审核员的 `ApplicationOperation.remark`，这是申请本身的属性） |

---

## 二、命名决策（重要，避免冲突）

工程内已存在 3 个相近的"备注/说明"概念，必须明确区分：

| 字段 | 归属 | 语义 | 写入者 |
|---|---|---|---|
| `applications.remark`（**新增**） | `applications` 表 | 学生备注（申请本身的属性） | 学生 |
| `applications.rule_info`（已存在） | `applications` 表 | rule 快照 | 学生（前端 build，服务端校验） |
| `ApplicationOperation.remark`（已存在） | `application_operation` 表 | 审核员操作备注（驳回原因 / 通过备注） | 审核员 / 学生 |

**决策**：本字段命名为 `student_remark`（数据库列） / `studentRemark`（Python 属性） / `studentRemark`（JSON camelCase 字段） / "学生备注"（UI）。

> ⚠️ **不要复用 `ApplicationPayload.remark` 字段**——该字段当前已在 `service.pass_application` / `reject_application` 中被当作"审核员备注"使用（写到 `ApplicationOperation.remark`），与学生备注的语义完全不同。

---

## 三、数据库改动

### 3.1 字段定义

```sql
-- ============================================================
-- 迁移：applications 表增加 student_remark 字段
-- 用途：学生在提交申请时录入的一段说明性文本（选填，≤500 字符）
-- 语义：随申请快照保存，审核员可在审核弹窗中查看
-- 日期：2026-08-15
-- ============================================================

ALTER TABLE applications
  ADD COLUMN IF NOT EXISTS student_remark VARCHAR(500);

COMMENT ON COLUMN applications.student_remark IS
  '学生备注（v1）：学生在提交申请时录入的说明性文本，选填，≤500 字符。'
  '申请快照属性，与 rule_info 平级，不进入 operation_log。';
```

**设计要点**：
- `VARCHAR(500)`：和前端 `maxlength` 对齐，超长时前端兜底拦截、后端二次校验。
- 可空 `NULL`：选填字段，旧数据保持 `NULL`，不需要 `DEFAULT`。
- 不加索引：备注字段不进查询条件，全表扫描时按 `id` 拉取即可。
- **不放入 `rule_info`**：两者语义独立；`rule_info` 是表单规则快照（机器可解析），备注是自由文本（人类阅读）。

### 3.2 迁移文件命名（沿用工程惯例）

参照 `migrations/2026-07-20_add_is_adjusted_to_application_proofs.sql` 与
`migrations/run_2026_07_20_add_is_adjusted.py` 的两份一组模式，需要新增：

```
migrations/2026-08-15_add_student_remark_to_applications.sql
migrations/run_2026_08_15_add_student_remark_to_applications.py
```

Python 迁移脚本需：
1. 用 `information_schema.columns` 检测列是否已存在 → **幂等**。
2. 支持 `--dry-run` 参数（与 `run_2026_07_20_add_is_adjusted.py` 一致）。
3. 失败回滚：`with sync_engine.begin()` 自动事务，异常即回滚。

---

## 四、后端改动（共 5 层）

### 4.1 Model 层 — `idbackend/src/models/application.py`

**改动点**：`Application` ORM 类新增一列映射。

```python
# 在 class Application(Base, TimestampMixin): 内，rule_info 之后追加
student_remark: Mapped[Optional[str]] = mapped_column(
    String(500),
    nullable=True,
    default=None,
)
```

**说明**：
- `Optional[str]`：字段可空，未填写时存 `None`。
- `String(500)`：与 DDL 对齐。
- 不需要注释（已在 DDL `COMMENT ON COLUMN` 中说明）。
- 不需要 `server_default`：NULL 即默认值。
- **不需要进 `__table_args__` 的索引列表**。

### 4.2 Schema 层（Request DTO） — `idbackend/src/app/schemas/application.py`

#### 4.2.1 `ApplicationPayload` 新增字段

当前结构（节选）：
```python
remark: Optional[str] = Field(default=None)
action: str = Field(default="save", ...)
```

**改动点**：在 `remark` 旁边新增 `studentRemark`，与已有字段平级。

```python
# ★ v10 新增：学生备注（仅学生端填写）
#  - save / submit / edit 时由前端填入
#  - 详情 / 列表 VO 中读取为 studentRemark
#  - 与 ApplicationPayload.remark（审核员备注）语义不同，不可复用
studentRemark: Optional[str] = Field(
    default=None,
    max_length=500,
    description="学生备注（选填，≤500 字符）",
)
```

#### 4.2.2 `ApplicationPayload.to_application_model` 新增赋值

当前：
```python
return Application(
    user_id=user_id,
    template_id=self.templateId,
    ...
    rule_info=self.ruleInfo or {},
)
```

**改动点**：新增一行。

```python
return Application(
    ...
    rule_info=self.ruleInfo or {},
    student_remark=self.studentRemark,        # ★ v10
)
```

#### 4.2.3 `ApplicationPayload.apply_to_model` 新增赋值

当前：
```python
def apply_to_model(self, app: Application, new_status: Optional[str] = None) -> None:
    app.template_id = self.templateId
    ...
    if self.ruleInfo is not None:
        app.rule_info = self.ruleInfo
    if new_status is not None:
        app.status = new_status
```

**改动点**：与 `rule_info` 处理方式一致——仅当 payload 显式提供时覆盖。

```python
def apply_to_model(self, app: Application, new_status: Optional[str] = None) -> None:
    ...
    if self.ruleInfo is not None:
        app.rule_info = self.ruleInfo
    if self.studentRemark is not None:
        app.student_remark = self.studentRemark     # ★ v10
    if new_status is not None:
        app.status = new_status
```

> **注意**：`studentRemark=None` 时 **不应** 清空已有备注——同 `ruleInfo` 语义一致，"未传" ≠ "置空"。
> 若未来需要"清空"语义，需另开字段（如 `studentRemark: str = ""` 显式赋值）。

### 4.3 Schema 层（Response VO） — `idbackend/src/app/schemas/application.py`

#### 4.3.1 `ApplicationVO` 新增字段 + ORM 转换

当前：
```python
class ApplicationVO(BaseModel):
    id: int
    userId: int
    userName: Optional[str] = None
    ...
    ruleInfo: dict[str, str] = Field(default_factory=dict)
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    proofs: List[ProofVO] = Field(default_factory=list)
```

**改动点**：新增 `studentRemark` 字段（驼峰 JSON 输出，与 `ruleInfo` 风格一致）。

```python
class ApplicationVO(BaseModel):
    ...
    ruleInfo: dict[str, str] = Field(default_factory=dict)
    studentRemark: Optional[str] = None            # ★ v10
    createdAt: Optional[str] = None
    ...
```

并在 `from_orm_to_vo` 中赋值：
```python
@classmethod
def from_orm_to_vo(cls, app, with_proofs: bool = False) -> "ApplicationVO":
    ...
    vo = cls(
        ...
        ruleInfo=app.rule_info or {},
        studentRemark=app.student_remark,           # ★ v10
        ...
    )
    if with_proofs:
        vo.proofs = [ProofVO.from_orm_to_vo(p) for p in (app.proofs or [])]
    return vo
```

#### 4.3.2 `__all__` 导出清单

无需新增导出（自动随类导出）。

### 4.4 Service 层 — `idbackend/src/services/application_service.py`

**核心改动点**：在 `save_draft` / `submit` / `edit_submit` 三个入口分别处理 `student_remark`。

#### 4.4.1 `save_draft` —— 新建分支

当前：
```python
if payload.applicationId is None:
    application = payload.to_application_model(
        user_id=user_id,
        status=ApplicationStatus.DRAFT.value,
    )
    application.rule_info = cleaned_rule_info
    await ApplicationRepository.insert(db, application)
    ...
```

**改动**：`to_application_model` 已经处理 `student_remark`，**此处不需要额外代码**。

#### 4.4.2 `save_draft` —— 更新分支

当前：
```python
else:
    application = await ApplicationRepository.get_with_details(
        db, payload.applicationId, for_update=True,
    )
    ...
    payload.apply_to_model(application, new_status=None)
    application.rule_info = cleaned_rule_info
    await ApplicationService._replace_proofs(db, application.id, payload.proofList)
```

**改动**：`apply_to_model` 已经处理 `student_remark`，**此处不需要额外代码**。

#### 4.4.3 `submit` —— 新建并提交

当前：
```python
application = payload.to_application_model(
    user_id=user_id,
    status=ApplicationStatus.APPLYING.value,
)
application.rule_info = cleaned_rule_info
await ApplicationRepository.insert(db, application)
```

**改动**：同上，`to_application_model` 已处理。**不需要额外代码**。

#### 4.4.4 `edit_submit` —— 编辑后提交

当前：
```python
event = application.submit(operator_id=user_id, operator_name=operator_name)
payload.apply_to_model(application)
if payload.ruleInfo is not None:
    cleaned_rule_info = await ApplicationService._build_rule_info(...)
    application.rule_info = cleaned_rule_info
await ApplicationService._replace_proofs(...)
```

**改动**：`apply_to_model` 已处理 `student_remark`。**不需要额外代码**。

#### 4.4.5 审核员端 —— `pass_application` / `reject_application`

**不需要改动**：审核员端只读 `application.student_remark`（通过 VO 自动返回），不做写入。

### 4.5 Route 层 — `idbackend/src/app/routes/application.py`

**不需要改动**：所有路由都共用 `ApplicationPayload`，新增字段后自动在 JSON 中传递。

---

## 五、学生端改动 — `idfrontend`

### 5.1 入口文件 `TemplateApplyDialog.vue`

#### 5.1.1 UI 位置（决策点）

`TemplateApplyDialog` 有两步：Step 1（条件匹配 + 得分）、Step 2（证明材料）。

**推荐位置**：Step 2 证明材料区下方，footer 之上，独立卡片"学生备注"。

理由：
- Step 1 是"选规则 + 看分"——决策性输入，备注属于补充说明，放在 Step 2 之后更自然；
- 与证明材料同属"提交信息"，与申请分/总分校验在同一上下文；
- 审核员在 `ApplicationCheckDialog` 的左侧 `el-descriptions` 区即可看到，不会破坏左右分栏布局。

#### 5.1.2 模板片段（设计稿）

在 `<!-- ===== Step 2：证明材料 ===== -->` 区块、`</el-alert>` 之后、`<!-- 列表 -->` 之前或之后插入：

```vue
<!-- v10：学生备注（选填，≤500 字符） -->
<section class="student-remark">
  <div class="remark-header">
    <span class="remark-title">学生备注</span>
    <span class="remark-sub">选填，可填写家庭特殊情况、成绩排名补充说明等</span>
  </div>
  <el-input
    v-model="studentRemark"
    type="textarea"
    :rows="4"
    :maxlength="500"
    show-word-limit
    placeholder="例如：家庭经济困难 / 单亲家庭 / 国家级竞赛获奖..."
  />
</section>
```

#### 5.1.3 Script 改动点

##### (a) `buildPayload` —— 把 `studentRemark` 加入 payload

当前：
```typescript
function buildPayload(action: 'save' | 'submit' | 'edit'): ApplicationPayload {
  return {
    applicationId: null,
    templateId: detail.value!.id,
    templateName: detail.value!.name,
    categoryId: detail.value!.categoryId,
    applyScore: scoreSummary.value.totalScore,
    proofList: proofItems.value.map(p => ({...})),
    remark: undefined,
    action,
    reviewCount: detail.value!.reviewCount ?? 1,
    ruleInfo: buildRuleInfo(),
  }
}
```

**改动**：
```typescript
function buildPayload(action: 'save' | 'submit' | 'edit'): ApplicationPayload {
  return {
    applicationId: null,
    templateId: detail.value!.id,
    templateName: detail.value!.name,
    categoryId: detail.value!.categoryId,
    applyScore: scoreSummary.value.totalScore,
    proofList: proofItems.value.map(p => ({...})),
    remark: undefined,                         // 审核员备注，本期不动
    studentRemark: studentRemark.value || undefined,   // ★ v10：学生备注
    action,
    reviewCount: detail.value!.reviewCount ?? 1,
    ruleInfo: buildRuleInfo(),
  }
}
```

##### (b) 新增 `studentRemark` 响应式状态

```typescript
const studentRemark = ref<string>('')
```

##### (c) `resetState` —— 清空备注

当前：
```typescript
function resetState() {
  detail.value = null
  ruleForms.value = []
  attributeGroups.value = []
  dialogStep.value = 1
  proofItems.value = []
  for (const k of Object.keys(groupSelections)) delete groupSelections[k]
  for (const k of Object.keys(transformSelections)) delete transformSelections[Number(k)]
}
```

**改动**：补一行 `studentRemark.value = ''`。

##### (d) 编辑重提场景 —— 回显备注

工程内已有 `ApplicationEditDialog.vue`（编辑已驳回/已撤回申请的场景），需要在该弹窗内也提供备注编辑能力。但**本次任务边界仅限 `TemplateApplyDialog.vue`**，所以编辑场景的备注回显方案有两种：

| 方案 | 描述 | 工作量 |
|---|---|---|
| **A. 本期最小化** | 仅在新建（submit / save）场景生效；编辑场景（`ApplicationEditDialog`）暂不渲染备注框，沿用旧备注 | 小 |
| **B. 全量对齐** | `ApplicationEditDialog.vue` 也加备注输入框，并在加载详情时回显 `detail.studentRemark` | 中 |

**决策**：**默认选 A**，如果你确认 B 再追加。

##### (e) `ApplicationPayload` 类型扩展 — `idfrontend/src/api/components/apiScore.ts`

当前：
```typescript
export interface ApplicationPayload {
  applicationId: number | null
  templateId: number
  templateName: string
  categoryId: number
  applyScore: number
  proofList: ProofPayload[]
  remark?: string
  action: 'save' | 'submit' | 'edit' | 'review'
  reviewAction?: 'pass' | 'reject'
  reviewCount?: number
  ruleInfo?: Record<string, string>
}
```

**改动**：
```typescript
export interface ApplicationPayload {
  ...现有字段...
  studentRemark?: string                    // ★ v10
}
```

并在 `ApplicationVO` / `ApplicationDetailVO` 中补：
```typescript
export interface ApplicationVO {
  ...现有字段...
  studentRemark?: string                    // ★ v10
}
```

### 5.2 学生端其他文件

| 文件 | 改动 |
|---|---|
| `idfrontend/src/views/template/components/TemplateApplyDialog.vue` | UI 输入框 + state + payload 注入 + reset 清空 |
| `idfrontend/src/api/components/apiScore.ts` | `ApplicationPayload` / `ApplicationVO` / `ApplicationDetailVO` 类型补 `studentRemark` 字段 |
| `idfrontend/src/views/application/components/ApplicationEditDialog.vue` | **本期可选**：编辑场景的备注回显与编辑 |
| `idfrontend/src/views/application/components/ApplicationDetailDialog.vue` | **建议**：在 `el-descriptions` 中增加一行"学生备注"显示（仅当非空时显示） |

---

## 六、审核员端改动 — `idfrontend-admin`

### 6.1 核心改动：`ApplicationCheckDialog.vue`

审核员在审核弹窗左侧需要看到学生备注。`el-descriptions` 区域（当前 5 列：学生/模板/状态/申请分/审核进度）需要扩展。

#### 6.1.1 模板改动

在现有 `el-descriptions` 区块内（status 项之后、申请分之前或之后）追加：

```vue
<el-descriptions :column="3" border>
  <el-descriptions-item label="学生">...</el-descriptions-item>
  <el-descriptions-item label="模板">{{ detail.templateName }}</el-descriptions-item>
  <el-descriptions-item label="状态">...</el-descriptions-item>
  <el-descriptions-item label="申请分">{{ detail.applyScore }} 分</el-descriptions-item>
  <el-descriptions-item label="审核进度">...</el-descriptions-item>

  <!-- ★ v10：学生备注（独立行，避免撑高 3 列） -->
  <el-descriptions-item label="学生备注" :span="3">
    <template v-if="detail.studentRemark">
      <pre class="remark-content">{{ detail.studentRemark }}</pre>
    </template>
    <span v-else class="text-muted">（无）</span>
  </el-descriptions-item>
</el-descriptions>
```

**样式补充**（`<style scoped>` 内）：
```css
.remark-content {
  margin: 0;
  padding: 0;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;       /* 保留换行 */
  word-break: break-word;      /* 超长折行 */
  max-height: 200px;
  overflow-y: auto;
}
```

#### 6.1.2 Script 改动

`ApplicationCheckDialog.vue` 已经通过 `getApplicationDetail(applicationId)` 加载详情，VO 中会自动包含 `studentRemark` 字段（因为后端 `ApplicationVO.from_orm_to_vo` 已经映射）。**不需要额外 script 改动**。

但 `ApplicationVO` 类型需要从 `@/api/modules/apiScore` 导入并新增字段（与学生端 `apiScore.ts` 同步）。

### 6.2 admin 端其他文件

| 文件 | 改动 |
|---|---|
| `idfrontend-admin/src/views/application/components/ApplicationCheckDialog.vue` | `el-descriptions` 区域增加"学生备注"行 |
| `idfrontend-admin/src/views/application/components/ApplicationCheckHistory.vue` | **建议**：列表/详情入口已自动支持，无需改 |
| `idfrontend-admin/src/api/modules/apiScore.ts` | `ApplicationVO` / `ApplicationDetailVO` 类型补 `studentRemark?: string` |

### 6.3 不需要改动的部分

- **审核员审核通过/驳回**：`pass_application` / `reject_application` 的 payload 中 `remark` 是审核员备注（→ 写到 `ApplicationOperation.remark`），与学生备注完全独立，不动。
- **撤回（revoke）**：管理员撤回已通过申请，逻辑不变。
- **列表查询**：`/api/admin/applications/my-pending` 等列表接口返回的 VO 自动包含 `studentRemark`，前端表格暂不展示（不在本期范围），仅详情弹窗展示。

---

## 七、测试 / 验证清单

### 7.1 后端单测 / 集成测

`idbackend/tests/` 下新增或扩展：

| 用例 | 期望 |
|---|---|
| `save_draft` 携带 `studentRemark="家庭困难"` | DB 中 `student_remark = "家庭困难"`，DRAFT 状态 |
| `submit` 不携带 `studentRemark`（前端字段为空） | DB 中 `student_remark = NULL` |
| `submit` 携带 `studentRemark="a"*501` | Pydantic `max_length=500` 校验失败 → 400 |
| `edit_submit` 携带新 `studentRemark` | DB 中 `student_remark` 更新为新值 |
| `edit_submit` 不携带 `studentRemark`（payload 为 None） | DB 中 `student_remark` **保持原值不变**（与 `ruleInfo` 语义一致） |
| 审核员 `pass_application` 后查询详情 | `ApplicationVO.studentRemark` 等于提交时的值 |

### 7.2 端到端流程

| 流程 | 步骤 |
|---|---|
| 学生新建并提交 | 填规则 → 填证明 → 填备注"家困" → 提交 → 学生详情能看到、审核员详情能看到 |
| 学生保存草稿 | 填备注 → 保存草稿 → 重开弹窗备注仍存在 |
| 学生取消并重提 | 已 APPLYING 取消 → 重新填备注 → 提交 |
| 审核员驳回后学生重提 | 驳回带原因 → 学生重提时备注框为空 → 提交 → 审核员看到新备注（与驳回原因互不干扰） |

### 7.3 数据库回滚

迁移脚本应支持幂等回滚：
```sql
ALTER TABLE applications DROP COLUMN IF EXISTS student_remark;
```

---

## 八、风险与决策点

### 8.1 风险

| 风险 | 缓解 |
|---|---|
| `ApplicationPayload.remark` 已存在，本次新增 `studentRemark` 容易混淆 | 文档、PR、commit message 明确区分；后端字段加注释；前端变量名 `studentRemark` 而非 `remark2` |
| 编辑场景（`ApplicationEditDialog`）本期不渲染备注框，可能导致旧备注"消失" | 选 A 方案时在 `apply_to_model` 用 `if self.studentRemark is not None` 判断；None 时不动 DB；旧备注保持不变 |
| 备注长度 500 是否合理 | 与前端 `maxlength` 对齐；若超长需求出现再扩 |
| 备注是否需要审核员可见（合规风险：是否泄露学生隐私） | 默认对审核员可见；如需保护可在 VO 层加权限过滤（不在本期） |
| 备注是否需要进操作日志（审计） | 当前不进；若需要可在 `submit` 流程同步写一条 `ApplicationOperation` 记录（不在本期） |

### 8.2 决策点（待确认）

| # | 决策点 | 选项 |
|---|---|---|
| 1 | 数据库字段名 | `student_remark`（推荐）/ `student_note` / `note` |
| 2 | 字段类型与长度 | `VARCHAR(500)`（推荐）/ `TEXT` / `VARCHAR(1000)` |
| 3 | 字段是否必填 | 选填（推荐）/ 必填 |
| 4 | UI 位置 | Step 2 证明材料下方（推荐）/ Step 1 得分上方 |
| 5 | 编辑场景备注框 | 本期不渲染（推荐 A）/ 全量对齐（B） |
| 6 | 是否进入审核员详情 | 是（推荐）/ 仅学生本人可见 |
| 7 | 是否进入操作日志 | 否（推荐）/ 是 |
| 8 | 审核员列表是否展示备注摘要 | 否（推荐本期不做）/ 是（截断前 30 字） |

---

## 九、改动文件汇总

| 层 | 文件 | 改动类型 |
|---|---|---|
| DB | `migrations/2026-08-15_add_student_remark_to_applications.sql` | 新增 |
| DB | `migrations/run_2026_08_15_add_student_remark_to_applications.py` | 新增 |
| Model | `idbackend/src/models/application.py` | `Application` 类新增 1 列映射 |
| Schema | `idbackend/src/app/schemas/application.py` | `ApplicationPayload` / `ApplicationVO` 新增字段 + 转换 |
| Service | `idbackend/src/services/application_service.py` | 无显式改动（依赖 `to_application_model` / `apply_to_model` 自动处理） |
| Route | `idbackend/src/app/routes/application.py` | 无改动 |
| Repo | `idbackend/src/repositories/application_repo.py` | 无改动 |
| 学生端 API | `idfrontend/src/api/components/apiScore.ts` | `ApplicationPayload` / `ApplicationVO` 类型扩展 |
| 学生端 UI | `idfrontend/src/views/template/components/TemplateApplyDialog.vue` | 新增备注输入框 + state + payload 注入 |
| 学生端详情 | `idfrontend/src/views/application/components/ApplicationDetailDialog.vue` | （建议）`el-descriptions` 增加"学生备注"行 |
| 学生端编辑 | `idfrontend/src/views/application/components/ApplicationEditDialog.vue` | （可选）编辑场景支持 |
| 审核员端 API | `idfrontend-admin/src/api/modules/apiScore.ts` | `ApplicationVO` 类型扩展 |
| 审核员端 UI | `idfrontend-admin/src/views/application/components/ApplicationCheckDialog.vue` | `el-descriptions` 增加"学生备注"行 |
| 测试 | `idbackend/tests/test_application_student_remark.py` | 新增（或合并到现有 test 文件） |

---

## 十、实施顺序建议

1. **DB 迁移**（DDL + Python 脚本 + `--dry-run` 验证）
2. **后端 Model + Schema**（含 VO / Payload 类型）
3. **后端 Service 行为验证**（curl / fastapi 调试）
4. **学生端 API 类型 + UI 输入框 + buildPayload 注入**
5. **学生端详情回显**（`ApplicationDetailDialog.vue`）
6. **审核员端 API 类型 + UI 展示**（`ApplicationCheckDialog.vue`）
7. **测试**（后端 + 端到端）

> 每一步可独立 commit / 独立验证。

---

## 附录 A：与已有字段的对照表（更新后）

| DB 列 | ORM 属性 | Payload 字段 | VO 字段 | UI 标签 |
|---|---|---|---|---|
| `rule_info` | `rule_info: dict` | `ruleInfo: dict[str, str]` | `ruleInfo: dict[str, str]` | （不进 UI 标签） |
| `student_remark`（**新**） | `student_remark: Optional[str]` | `studentRemark: Optional[str]` | `studentRemark: Optional[str]` | "学生备注" |
| — | — | `remark: Optional[str]` | — | "审核备注"（写到 `application_operation.remark`） |
| — | — | — | — | "驳回原因"（写到 `application_operation.remark`） |

---

## 附录 B：版本号约定

- 数据库 DDL 注释标注 `v1`（不与 `rule_info` 的 `v7` 混用，因为 `rule_info` 的 v7 是 rule 快照自身的版本）
- 业务代码注释标注 `★ v10`（沿用工程内现有的 `★ v7`、`★ v9` 注释惯例，参见 `application.py` 中 `★ v7 字段`）
- API 字段命名带 `v10` 仅在 commit message 中提及，不写入代码注释

---

> ✅ **请确认本文档 8.2 节 8 个决策点**（特别是 #1、#4、#5、#6），确认后再开始实施。