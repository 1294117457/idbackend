---

# ExtraInfoField 学生扩展字段功能设计

> 本文档为 `extra_info_field` 表与相关功能的**具体实现设计文档**，与 `四层职责设计.md` 中的概念层对齐。
> 代码实现尚未落盘，仅描述 ORM 模型、Service 接口、Router 接口、前端交互等设计蓝图。

---

## 一、需求背景

`user` 表预留了 `extra_info jsonb` 字段，用于存储学生的动态扩展信息，如：
- 英语四六级成绩（CET-4、CET-6）
- 游泳水平
- 计算机等级
- 特长认证
- ……（老师按需配置）

现有问题：
- 字段含义、类型、是否必填都不明确
- 无法在管理端灵活增删字段
- 学生端无编辑入口

---

## 二、最终表结构

```sql
CREATE TABLE extra_info_field (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(128)  NOT NULL,                  -- 显示名，如"四六级分数"
    type        VARCHAR(20)   NOT NULL DEFAULT 'TEXT',    -- TEXT / NUMBER / SELECT / DATE
    options     JSONB        DEFAULT '[]'::jsonb,         -- type=SELECT 时的选项列表，如 ["优秀","良好","及格"]
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    sort_order  INTEGER      NOT NULL DEFAULT 0,
    description VARCHAR(255),
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);

COMMENT ON COLUMN extra_info_field.type IS 'TEXT=文本输入, NUMBER=数字输入, SELECT=下拉选择, DATE=日期选择';
COMMENT ON COLUMN extra_info_field.options IS 'type=SELECT 时有效，存储选项列表 JSON 数组';

-- user.extra_info 存储结构（jsonb）：
-- {
--     "f_1": 425,          -- f_{id}: NUMBER 类型
--     "f_2": "pass",       -- f_{id}: SELECT 类型
--     "f_3": "2025-06-01"  -- f_{id}: DATE 类型
-- }

-- 索引（按字段值查询时用到）
CREATE INDEX idx_user_extra_info ON users USING gin (extra_info);
```

### 2.1 字段设计说明

| 字段 | 说明 |
|------|------|
| `id` | 唯一主键，作为 `extra_info` 中的 key 后缀（`f_{id}`） |
| `name` | 展示给用户的中文名，不做唯一约束（允许同名？） |
| `type` | 字段类型，控制前端渲染组件 |
| `options` | 仅 `SELECT` 类型使用，存选项列表 |
| `is_active` | 启用/停用；停用后管理端列表消失，学生端也不展示 |
| `sort_order` | 控制管理端列表和学生端展示的顺序 |

> **为什么用 `f_{id}` 而不是 `field_key`**：字段名（name）可以改，但 id 永远不变。用 id 做 key，name 改了不影响存量数据，也不需要迁移。

### 2.2 type 对应前端组件

| type | 学生端编辑组件 | 备注 |
|------|--------------|------|
| TEXT | `<el-input>` | 单行文本 |
| NUMBER | `<el-input-number>` | 数字，支持 min/max |
| SELECT | `<el-select>` | 下拉，选项从 options 读 |
| DATE | `<el-date-picker type="date">` | 日期 |

---

## 三、数据模型层（ORM）

新文件：`src/models/extra_info_field.py`

```python
"""学生扩展字段模型"""
from sqlalchemy import String, Integer, ForeignKey, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional, List

from .base import Base, TimestampMixin


class ExtraInfoField(Base, TimestampMixin):
    """extra_info_field 表"""
    __tablename__ = "extra_info_field"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="TEXT"
    )  # TEXT / NUMBER / SELECT / DATE
    options: Mapped[list] = mapped_column(JSON, default=list)  # SELECT 类型的选项列表
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[Optional[str]] = mapped_column(String(255))
```

---

## 四、Service 层（业务编排）

新文件：`src/services/extra_info_field_service.py`

### 4.1 错误定义

```python
class ExtraInfoFieldError(Exception): ...
class FieldNotFound(ExtraInfoFieldError): ...
class FieldTypeInvalid(ExtraInfoFieldError):
    """type 不在允许范围内"""
class FieldNameDuplicate(ExtraInfoFieldError):
    """name 重复（可选，按业务需求决定是否校验）"""
```

### 4.2 读接口

```python
class ExtraInfoFieldService:

    @staticmethod
    async def get_active_fields(db: AsyncSession) -> List[ExtraInfoField]:
        """
        获取所有 is_active=TRUE 的字段，供学生端展示/编辑使用。
        按 sort_order ASC, id ASC 排序。
        """

    @staticmethod
    async def get_all_fields(
        db: AsyncSession, *, include_inactive: bool = False
    ) -> List[ExtraInfoField]:
        """
        管理端使用。include_inactive=True 时返回全部，否则仅返回 is_active=TRUE。
        按 sort_order ASC, id ASC 排序。
        """

    @staticmethod
    async def get_by_id(db: AsyncSession, field_id: int) -> Optional[ExtraInfoField]: ...

    @staticmethod
    async def get_field_options(db: AsyncSession, field_id: int) -> Optional[list]:
        """获取指定字段的 options（SELECT 类型下拉选项）"""
```

### 4.3 写接口

```python
class ExtraInfoFieldService:

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        name: str,
        type: str,           # TEXT / NUMBER / SELECT / DATE
        options: Optional[list] = None,
        sort_order: int = 0,
        description: Optional[str] = None,
    ) -> ExtraInfoField:
        """
        创建字段：
        1. 校验 type 在允许范围内，否则抛 FieldTypeInvalid
        2. 若 type != SELECT，options 必须为空列表
        3. 写入并返回
        """

    @staticmethod
    async def update(
        db: AsyncSession,
        field_id: int,
        *,
        name: Optional[str] = None,
        type: Optional[str] = None,
        options: Optional[list] = None,
        sort_order: Optional[int] = None,
        is_active: Optional[bool] = None,
        description: Optional[str] = None,
    ) -> ExtraInfoField:
        """
        更新字段：
        1. 校验 type 在允许范围内
        2. 若 type != SELECT，options 强制设为 []
        3. 若 is_active 从 True 改 False，学生端立即消失（不删存量数据）
        """

    @staticmethod
    async def delete(db: AsyncSession, field_id: int) -> None:
        """
        删除字段：
        1. 不强制删 user.extra_info 中的旧值（f_{id} 残留无害，前端按 is_active 过滤）
        2. 可选：清理残留的 f_{id} 值（见 FAQ）
        """
```

---

## 五、Router 层（HTTP 接口）

新文件：`src/app/routes/extra_info_field.py`

### 5.1 接口清单

| Method | Path | 权限码 | 用途 |
|--------|------|--------|------|
| GET | `/api/extra-info-field` | `extra_info_field:read` | 管理端获取字段列表 |
| GET | `/api/extra-info-field/active` | `user:read`（学生端用） | 获取已启用的字段定义 |
| GET | `/api/extra-info-field/{id}` | `extra_info_field:read` | 获取单个字段详情 |
| POST | `/api/extra-info-field` | `extra_info_field:create` | 创建字段 |
| PUT | `/api/extra-info-field/{id}` | `extra_info_field:update` | 修改字段 |
| DELETE | `/api/extra-info-field/{id}` | `extra_info_field:delete` | 删除字段 |

### 5.2 Request / Response Schema（pydantic）

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import date


class ExtraInfoFieldCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    type: Literal["TEXT", "NUMBER", "SELECT", "DATE"] = Field(
        default="TEXT", description="字段类型"
    )
    options: Optional[List[str]] = Field(
        None, description="SELECT 类型的下拉选项，type=SELECT 时必填"
    )
    sort_order: int = Field(0, ge=0)
    description: Optional[str] = Field(None, max_length=255)

    class Config:
        extra = "forbid"


class ExtraInfoFieldUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    type: Optional[Literal["TEXT", "NUMBER", "SELECT", "DATE"]] = None
    options: Optional[List[str]] = None
    sort_order: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None
    description: Optional[str] = Field(None, max_length=255)

    class Config:
        extra = "forbid"
```

### 5.3 路由骨架

```python
router = APIRouter(prefix="/api/extra-info-field", tags=["学生扩展字段管理"])


@router.get("")
async def list_fields(
    includeInactive: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """管理端获取字段列表"""
    fields = await ExtraInfoFieldService.get_all_fields(
        db, include_inactive=includeInactive
    )
    return R.success_resp([_serialize(f) for f in fields])


@router.get("/active")
async def get_active_fields(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """学生端获取已启用的字段定义"""
    fields = await ExtraInfoFieldService.get_active_fields(db)
    return R.success_resp([_serialize(f) for f in fields])


@router.post("")
async def create_field(
    data: ExtraInfoFieldCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        field = await ExtraInfoFieldService.create(db, **data.model_dump())
    except FieldTypeInvalid as e:
        return R.bad_request_resp(str(e))
    return R.created_resp(_serialize(field))


@router.put("/{field_id}")
async def update_field(
    field_id: int,
    data: ExtraInfoFieldUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        field = await ExtraInfoFieldService.update(db, field_id, **data.model_dump(exclude_unset=True))
    except FieldNotFound:
        return R.not_found_resp("字段不存在")
    except FieldTypeInvalid as e:
        return R.bad_request_resp(str(e))
    return R.success_resp(_serialize(field))


@router.delete("/{field_id}")
async def delete_field(field_id: int, db: AsyncSession = Depends(get_db)):
    try:
        await ExtraInfoFieldService.delete(db, field_id)
    except FieldNotFound:
        return R.not_found_resp("字段不存在")
    return R.success_resp({"msg": "删除成功"})


def _serialize(f: ExtraInfoField) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "type": f.type,
        "options": f.options or [],
        "sortOrder": f.sort_order,
        "isActive": f.is_active,
        "description": f.description,
    }
```

---

## 六、学生端：我的成绩页面改造

文件：`idfrontend/src/views/score/MyScore.vue`

### 6.1 字段展示区域

在现有成绩展示基础上，新增"扩展信息"区块：

```
┌──────────────────────────────────────────────────────────────┐
│  我的成绩                                                     │
│                                                              │
│  [基本信息]              [扩展信息]                    [编辑] │
│  姓名：张三             四六级分数：425 分                   │
│  学号：2021001234       游泳水平：达标                       │
│  专业：计算机科学与技术  计算机等级：二级                     │
│  年级：大三                                            [编辑] │
└──────────────────────────────────────────────────────────────┘
```

### 6.2 字段定义获取（学生端）

```typescript
// 1. 页面加载时获取字段定义
const extraFields = ref<ExtraInfoField[]>([])

const loadExtraFields = async () => {
  const res = await getActiveExtraInfoFields()
  extraFields.value = res.data
}

// 2. 获取当前用户的 extra_info
const userExtraInfo = ref<Record<string, any>>({})

const loadUserExtraInfo = async () => {
  const res = await getCurrentUserExtraInfo()
  userExtraInfo.value = res.data.extraInfo || {}
}
```

### 6.3 编辑弹窗设计

点击 [编辑] 弹出 `el-dialog`，根据字段 type 渲染对应组件：

```vue
<el-dialog v-model="editDialogVisible" title="编辑扩展信息" width="500px">
  <el-form :model="editForm" label-width="120px">
    <el-form-item
      v-for="field in extraFields"
      :key="field.id"
      :label="field.name"
    >
      <!-- TEXT -->
      <el-input
        v-if="field.type === 'TEXT'"
        v-model="editForm[`f_${field.id}`]"
        placeholder="请输入"
      />

      <!-- NUMBER -->
      <el-input-number
        v-else-if="field.type === 'NUMBER'"
        v-model="editForm[`f_${field.id}`]"
        :min="0"
        :max="999"
        controls-position="right"
      />

      <!-- SELECT -->
      <el-select
        v-else-if="field.type === 'SELECT'"
        v-model="editForm[`f_${field.id}`]"
        placeholder="请选择"
      >
        <el-option
          v-for="opt in field.options"
          :key="opt"
          :label="opt"
          :value="opt"
        />
      </el-select>

      <!-- DATE -->
      <el-date-picker
        v-else-if="field.type === 'DATE'"
        v-model="editForm[`f_${field.id}`]"
        type="date"
        placeholder="选择日期"
        value-format="YYYY-MM-DD"
      />
    </el-form-item>
  </el-form>

  <template #footer>
    <el-button @click="editDialogVisible = false">取消</el-button>
    <el-button type="primary" @click="submitExtraInfo">保存</el-button>
  </template>
</el-dialog>
```

### 6.4 保存逻辑

```typescript
const submitExtraInfo = async () => {
  await updateUserExtraInfo({ extraInfo: editForm })
  editDialogVisible.value = false
  await loadUserExtraInfo()
  ElMessage.success('保存成功')
}
```

---

## 七、管理端：ExtraInfoFieldSetting 页面

文件：`idfrontend-admin/src/views/student/ExtraInfoFieldSetting.vue`

### 7.1 页面布局

```
┌──────────────────────────────────────────────────────────┐
│  学生扩展字段设置                    [+新增字段]         │
├──────────────────────────────────────────────────────────┤
│  [正常] [已停用]                                         │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │ # │ 字段名称   │ 类型   │ 选项         │ 排序 │ 操作 │  │
│  ├───┼───────────┼────────┼──────────────┼──────┼──────┤  │
│  │ 1 │ 四六级分数 │ NUMBER │      —       │  1   │ 编辑 │  │
│  │ 2 │ 游泳水平   │ SELECT │ 达标/未达标  │  2   │ 编辑 │  │
│  │ 3 │ 计算机等级 │ SELECT │ 一级/二/三/四│  3   │ 编辑 │  │
│  │ 4 │ 备注       │ TEXT   │      —       │  4   │ 编辑 │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  [上一页] [1/1] [下一页]                                  │
└──────────────────────────────────────────────────────────┘
```

### 7.2 新建/编辑字段弹窗

```
┌────────────────────────────────────────────────────┐
│  {{ isEdit ? '编辑字段' : '新建字段' }}          ×│
├────────────────────────────────────────────────────┤
│  字段名称：  ┌────────────────────────────────┐   │
│             │ 四六级分数                      │   │
│             └────────────────────────────────┘   │
│                                                    │
│  字段类型：  ○ TEXT（文本）                        │
│             ○ NUMBER（数字）                       │
│             ○ SELECT（下拉选择）                    │
│             ○ DATE（日期）                         │
│                                                    │
│  下拉选项：  （仅 SELECT 显示）                     │
│             ┌────────────────────────────────┐   │
│             │ 优秀                           ✕ │   │
│             │ 良好                           ✕ │   │
│             │ 及格                           ✕ │   │
│             │ [+ 添加选项]                    │   │
│             └────────────────────────────────┘   │
│                                                    │
│  排序：      ┌──────┐                              │
│             │  1   │  （数字越小越靠前）             │
│             └──────┘                                │
│                                                    │
│  描述：      ┌────────────────────────────────┐   │
│             │                                │   │
│             └────────────────────────────────┘   │
│                                                    │
│            [取消]              [确定]              │
└────────────────────────────────────────────────────┘
```

### 7.3 操作交互

| 操作 | API | 说明 |
|------|-----|------|
| 查看列表 | GET `/api/extra-info-field` | 分页，支持 includeInactive 切换 |
| 新建 | POST `/api/extra-info-field` | 字段类型切换时清空/填入 options |
| 编辑 | PUT `/api/extra-info-field/{id}` | 同新建弹窗，回填数据 |
| 停用 | PUT `/api/extra-info-field/{id}` | is_active=false，学生端消失 |
| 启用 | PUT `/api/extra-info-field/{id}` | is_active=true |
| 删除 | DELETE `/api/extra-info-field/{id}` | 二次确认；存量数据残留（按 id 过滤不展示） |

---

## 八、FAQ

### Q1: 删字段后，user.extra_info 中的旧值如何处理？

**推荐方案：保留残留，不清理。**

理由：
- 清理需要遍历所有用户，开销大
- `f_{id}` 残留无害，前端按 `is_active` 过滤不会展示
- 如果以后要恢复，只需把 `is_active` 改回 true，旧值自动可用

**可选方案：软删除** —— 把 `DELETE` 改成 `UPDATE is_active=FALSE`，历史可追溯。

### Q2: 为什么不在 `extra_info_field` 表加一列存每个字段的 key（如 cet4）？

不需要。id 已经是稳定标识，`f_{id}` 就是 key。如果未来需要通过 key 查字段（比如 API 对接），可以在 service 层加一个 `get_by_key` 方法动态生成 key，不改表结构。

### Q3: type 为什么用 VARCHAR 而不是 ENUM？

PostgreSQL 的 ENUM 修改代价大（要 `ALTER TYPE`），VARCHAR 够用，service 层校验更灵活。

### Q4: 学生端按字段搜索（管理员在学生列表过滤）？

目前 `extra_info` 是 jsonb，可以直接在 `user` 表上建 GIN 索引按 `f_{id}` 查询：

```sql
-- 查四六级分数>=425的学生
SELECT * FROM users
WHERE extra_info ->> 'f_1' >= '425';
-- 查游泳"达标"的学生
SELECT * FROM users
WHERE extra_info ->> 'f_2' = '达标';
```

如需在学生列表页面加字段筛选 UI，可扩展 `GET /api/user/admin/list` 参数，或单独加 `GET /api/user/extra-info/search` 接口。

### Q5: 字段重命名后，旧值会丢失吗？

不会。用 id 做 key，name 只是展示用的 label，改 name 不影响 `extra_info` 中存的 `f_{id}` 值。

---

## 九、Alembic 迁移

```python
# migrations/xxx_add_extra_info_field.py

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

op.create_table(
    "extra_info_field",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("name", sa.String(128), nullable=False),
    sa.Column("type", sa.String(20), nullable=False, server_default="TEXT"),
    sa.Column("options", JSONB, server_default="[]"),
    sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("description", sa.String(255), nullable=True),
    sa.Column("created_at", sa.DateTime(), nullable=True),
    sa.Column("updated_at", sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint("id"),
)

op.create_index(
    "idx_extra_info_field_sort",
    "extra_info_field",
    ["sort_order", "id"],
)
```

---

## 十、设计取舍

| 主题 | 当前决策 | 未来可扩展 |
|------|---------|-----------|
| 字段唯一标识 | `f_{id}`（id 做 key） | 如需可加 `field_key` 列 |
| SELECT 选项存储 | `options JSONB` 数组 | 如需区分 label/value 可改成 `[{label, value}]` |
| 删除字段 | 不清理 extra_info 残留 | 可改软删除 |
| 字段重名 | 允许（name 无唯一约束） | 如需可加唯一约束 |
| 必填校验 | 暂不实现 | 可加 `required BOOLEAN` 字段 |
| 学生端搜索 | 不做 | 可扩展 list 接口加 filter 参数 |
