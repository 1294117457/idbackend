# 前端统一错误提示 + 全局 Loading 方案（草案）

> **状态**：草案，待评审后再实施
> **适用范围**：`idfrontend-admin`（管理端）**与** `idfrontend`（学生端）**同步改造**
> **目标**：
> 1. 后端返回的 `msg` 由 HTTP 层统一弹窗，业务组件不再写 `ElMessage.error(...)`
> 2. 提供一个"全局共享"的 loading 指示器，所有请求共用一个计数
> 3. 进度条使用 Element Plus `el-progress` 组件

---

## 0. 名词解释（评审前对齐概念）

| 术语 | 含义 |
|---|---|
| **apiClient** | `src/common/utils/http.ts` 里 `axios.create(...)` 创建的 axios 实例，**导出名为 `apiClient`（管理端 default export）**。组件里 `import apiClient from '@/utils/http'` 或 `import { apiClient } from '@common/utils/http'` 拿到的就是这个实例。业务层所有 `apiClient.get/post/...` 都经过它的拦截器。 |
| **useRequest** | 提案中**可选**的 composable，用来消灭 `try/finally` 样板代码。形态是 `const { loading, run } = useRequest()`，调用方 `run(async () => { ... })` 自动维护 loading 状态。注意这是**前端自定义的工具函数**，与 axios、element-plus 无关。 |
| **http 拦截器** | `apiClient.interceptors.request.use / response.use` 注册的两个回调，分别在请求发出前、响应回来后统一处理（加 token、统一弹错误、统一 loading 计数等）。 |
| **全局 Loading** | Pinia store `useLoadingStore`，HTTP 拦截器只负责 `add() / sub()` 维护 `pending` 计数，UI 层（`<GlobalProgress />`）根据 `visible` 决定是否渲染。 |
| **局部 Loading** | 组件内 `const loading = ref(false)`，绑定到 `el-table v-loading` / `el-button :loading` / 弹窗内的 `v-loading`。与全局 Loading **共存不冲突**。 |

---

## 1. 现状摘要

参考文件：
- `idfrontend-admin/src/common/utils/http.ts`（共 151 行）
- `idfrontend/src/common/utils/http.ts`（学生端，与管理端逻辑**完全一致**）
- `idfrontend-admin/src/views/template/scoreTemplate.vue:476-519` 等业务组件

**现状问题**：

| 问题 | 具体表现 |
|---|---|
| 业务代码手动弹错误窗 | 每个 fetch 函数都重复写 `ElMessage.error(resp.msg \|\| '加载xxx失败')`（见 `scoreTemplate.vue:503`、`:516`） |
| 成功消息也由拦截器弹 | 当前 `http.ts:87-89` 已对**非 GET 请求**自动 `ElMessage.success(res.msg)`，这条保留 |
| 失败提示口径不一 | 有的写"加载失败"、有的写"网络异常"、有的 fallback 字符串不一致 |
| Loading 各自为政 | 每个组件用独立 `loading.value` 控制 `el-table` 的 `v-loading`，多个并发请求时无法在顶层感知"系统还在干活" |
| 弹窗内 loading | 详情弹窗（dialog）的 loading 与表格 loading 没法联动，骨架屏体验差 |
| **管理端与学生端实现不一致** | 学生端早期 re-export 管理端的 `@common/utils/http`，长期演进可能漂移 |

**已经做对的事**（不要回退）：
- ✅ `http.ts` 已经在拦截器里统一弹错误，**业务组件不必再写**
- ✅ 401/403 已经在拦截器里跳登录 + token 刷新

---

## 2. 目标

| # | 目标 | 度量 |
|---|---|---|
| G1 | 后端 `msg` 由 HTTP 层统一弹 | 业务组件 grep 不到 `ElMessage.error` |
| G2 | 顶部有一个 Element Plus 全局 loading 指示器 | 任意请求 in-flight 时显示，并发正确 |
| G3 | 业务代码 `try { ... } finally { loading = false }` 仍保留给**局部** loading（表格、弹窗） | 局部 loading 由组件自治 |
| G4 | 弹窗 + loading 联动 | 先开 dialog → 内容区 `v-loading="dialogLoading"` → 骨架屏自然过渡 |
| G5 | 管理端 / 学生端改造**同步推进** | 两端 `http.ts` 保持一致 |

---

## 3. 方案 A：错误统一弹窗（最小改动）

### 3.1 已有的实现

`http.ts:81-84` 已经满足：

```ts
const isSuccess = res.code === 200 || res.code === 0 || res.code === 201
if (!isSuccess) {
  ElMessage.error(res.msg || '请求失败')
  return Promise.reject(res)
}
```

### 3.2 要做的两件事

**(1) 给拦截器加 `silent` 配置项**

当前：所有非 GET 请求自动 `ElMessage.success(res.msg)`。
问题：
- 上传 / 批量导入等接口，后端 msg 很长，业务方想自定义措辞时无法关闭
- 部分接口成功后 msg 是给 log 看的，不是给用户看的

调整方案（保留默认，但允许 opt-out）：

```ts
// 在请求 config 上加一个静默标记
apiClient.post(url, data, { silent: true })

// 拦截器里：
const silent = (response.config as any).silent === true
const method = response.config.method?.toLowerCase()
if (method !== 'get' && res.msg && !silent) {
  ElMessage.success(res.msg)
}
```

业务侧用法：
```ts
// 默认会弹成功
await apiClient.post('/api/template', payload)

// 这个接口自己控制 toast
await apiClient.post('/api/template/import', form, { silent: true })
```

**(2) 把"业务组件手动弹错误"的代码全部删掉**

具体清单（评审时核对）：
- `idfrontend-admin/src/views/template/scoreTemplate.vue:503, 516`
- `idfrontend-admin/src/views/template/scoreAttribute.vue` 内若干处
- `idfrontend-admin/src/views/template/rule.vue` 内若干处
- `idfrontend-admin/src/views/template/templateCategory.vue` 内若干处
- `idfrontend/src/views/template/index.vue` 同类 `ElMessage.error`

这些文件里 `if (resp.code !== 200) ElMessage.error(...)` 模式全部删除，因为拦截器已经处理了。

**注意**：
- 拦截器走 `return Promise.reject(res)`，调用方仍能 `catch` 到
- 如果某处真的需要差异化处理（例如批量校验失败，要弹一个表格而不是 toast），用 `silent: true` 关闭默认弹窗，自己处理

---

## 4. 方案 B：全局共享 Loading（重点）

### 4.1 设计

引入一个 Pinia store，**HTTP 拦截器只负责维护计数器**，UI 层决定怎么渲染：

```
HTTP 拦截器 ──add/sub──► useLoadingStore ──visible──► <GlobalProgress />
                                                      │
                                                      └─ 顶部 el-progress indeterminate
```

#### Store：`src/stores/loading.ts`（管理端 + 学生端各一份，内容相同）

```ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useLoadingStore = defineStore('loading', () => {
  const pending = ref(0)
  const visible = computed(() => pending.value > 0)

  function add() {
    pending.value++
  }
  function sub() {
    pending.value = Math.max(0, pending.value - 1)
  }
  function reset() {
    pending.value = 0
  }

  return { pending, visible, add, sub, reset }
})
```

#### HTTP 拦截器改造：`http.ts`（管理端 + 学生端同步改）

```ts
import { useLoadingStore } from '@/stores/loading'

apiClient.interceptors.request.use(
  (config) => {
    useLoadingStore().add()
    // 现有 token 注入...
    return config
  },
  (error) => {
    useLoadingStore().sub()
    return Promise.reject(error)
  },
)

apiClient.interceptors.response.use(
  (response) => {
    useLoadingStore().sub()
    // 现有 success / 401 处理...
    return res
  },
  (error) => {
    useLoadingStore().sub()
    // 现有错误处理...
    return Promise.reject(error)
  },
)
```

#### 顶栏组件：`src/components/GlobalProgress.vue`（使用 Element Plus `el-progress`）

```vue
<script setup lang="ts">
import { useLoadingStore } from '@/stores/loading'
const loadingStore = useLoadingStore()
</script>

<template>
  <Transition name="fade">
    <div v-if="loadingStore.visible" class="global-progress">
      <el-progress
        :percentage="100"
        :indeterminate="true"
        :duration="1.2"
        :stroke-width="3"
        color="#409eff"
        :show-text="false"
      />
    </div>
  </Transition>
</template>

<style scoped>
.global-progress {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9999;
  pointer-events: none;
}
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
```

要点：
- 使用 `<el-progress :indeterminate="true">`，Element Plus 内置"来回滑动"动画，无需手写 keyframes
- 顶部 3px，不挡内容、不挡 click
- 通过 `<Transition>` 让淡入淡出顺滑

#### 挂载点：`src/App.vue` 或 `src/layout/...` 顶层（管理端 + 学生端各挂一份）

```vue
<template>
  <el-config-provider>
    <GlobalProgress />
    <router-view />
  </el-config-provider>
</template>
```

### 4.2 行为约定

| 场景 | 表现 |
|---|---|
| 单个请求 in-flight | 顶部 3px el-progress 出现，indeterminate 动画 |
| 3 个请求并发，全部 pending | el-progress 持续显示，直到 `pending === 0` |
| 3 个并发，第 2 个 fail | 进度条仍在（count 仍 > 0），错误 toast 由拦截器统一弹 |
| 路由切换前有未完成请求 | 进度条继续显示（HMR / 浏览器导航不影响 store） |
| 401 全局跳登录 | 进度条自动清空（`clearTokensAndRedirect` 后手动 `loadingStore.reset()`，可选） |

### 4.3 局部 loading 与全局 loading 共存

| 区域 | 谁负责 | UI 控件 |
|---|---|---|
| **全局** | `useLoadingStore` | `<GlobalProgress />` 顶部 `el-progress` |
| **表格 / 列表** | 组件 `const loading = ref(false)` | `<el-table v-loading="loading">` |
| **详情弹窗** | 组件 `const dialogLoading = ref(false)` | `<div v-loading="dialogLoading">` 包内容 |
| **卡片 / 按钮** | 组件 `loading` | `<el-button :loading="loading">` |

两者**不冲突**：
- 全局进度条：用户进入页面 / 切换 tab 时感知"系统干活"
- 局部 loading：精准控制按钮 / 表格 / 弹窗区

---

## 5. 弹窗 + Loading 联动（推荐写法）

以 `scoreTemplate.vue` 的详情弹窗为例：

### 5.1 现状（不推荐）

```ts
const viewDetail = async (id: number) => {
  const resp = await getTemplateDetail(id)
  if (resp.code === 200) {
    detail.value = resp.data
    detailDialogVisible.value = true
  } else {
    ElMessage.error(resp.msg || '加载详情失败')  // ← 拦截器已经弹了
  }
}
```

问题：
- 失败处理交给拦截器后，else 分支其实是死代码
- 弹窗在请求成功后**才**打开，体感上"点了没反应"

### 5.2 改造后（推荐）

```ts
const detailDialogVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<TemplateDetail | null>(null)

const viewDetail = async (id: number) => {
  // 1. 先打开弹窗（空骨架）
  detailDialogVisible.value = true
  detailLoading.value = true
  detail.value = null

  try {
    const resp = await getTemplateDetail(id)
    if (resp.code === 200) {
      detail.value = resp.data
    }
    // 失败由 http 拦截器统一 toast，业务侧不必处理
  } finally {
    detailLoading.value = false
  }
}
```

模板：

```vue
<el-dialog v-model="detailDialogVisible" title="模板详情" width="720px">
  <div v-loading="detailLoading" element-loading-text="加载详情中..." class="detail-body">
    <template v-if="detail">
      <!-- 详情内容 -->
      <h3>{{ detail.name }}</h3>
      <p>说明：{{ detail.description }}</p>
      <!-- rule / attribute 树 -->
    </template>
  </div>
</el-dialog>
```

效果：
1. 点击 → 弹窗**立刻**出现（避免"点了没反应"）
2. 弹窗内 `v-loading` 自动展示骨架屏
3. 请求完成 → 骨架屏消失，真实内容淡入
4. 失败 → 顶部进度条消失 + 错误 toast + **业务侧可选地手动关闭弹窗**（`detailDialogVisible = false`）

### 5.3 失败时是否自动关弹窗？

**默认不要自动关**。失败后让用户看到弹窗上下文、自己决定关掉，体验更好。但可以在 catch 里做：

```ts
} catch (e) {
  detailDialogVisible.value = false  // 拉取失败直接关掉
} finally {
  detailLoading.value = false
}
```

建议：**不要**自动关，因为拦截器已经 toast 了，让用户能从弹窗上下文回到原页面。

---

## 6. 进一步：消灭 try/finally 样板（可选）

如果每个函数都写 `loading.value = true; try { ... } finally { loading.value = false }` 太啰嗦，抽一个 composable：

### `src/composables/useRequest.ts`（管理端 + 学生端各一份，内容相同）

```ts
import { ref, type Ref } from 'vue'

export function useRequest() {
  const loading = ref(false)

  const run = async <T>(fn: () => Promise<T>): Promise<T | undefined> => {
    loading.value = true
    try {
      return await fn()
    } finally {
      loading.value = false
    }
  }

  return { loading: loading as Ref<boolean>, run }
}
```

调用方：

```ts
const { loading, run } = useRequest()
const loadTemplates = () => run(async () => {
  const resp = await getTemplateList(...)
  if (resp.code === 200) templateList.value = resp.data?.list ?? []
})
```

模板照旧用 `v-loading="loading"`。**这个 composable 是可选的**，评审时再决定要不要引入。

---

## 7. 改动清单（评审后再实施）

### 7.1 管理端 `idfrontend-admin`

| # | 文件 | 改动 | 风险 |
|---|---|---|---|
| 1 | `src/common/utils/http.ts` | 加 `silent` 配置支持；引入 `useLoadingStore` add/sub | 低 |
| 2 | `src/stores/loading.ts` | 新建 | 无 |
| 3 | `src/components/GlobalProgress.vue` | 新建（用 `el-progress`） | 无 |
| 4 | `src/App.vue` 或顶层 layout | 挂载 `<GlobalProgress />` | 低 |
| 5 | `src/views/template/scoreTemplate.vue` | 删除 `ElMessage.error`；detail 弹窗加 `v-loading` | 低 |
| 6 | `src/views/template/scoreAttribute.vue` | 同上 | 低 |
| 7 | `src/views/template/rule.vue` | 同上 | 低 |
| 8 | `src/views/template/templateCategory.vue` | 同上 | 低 |
| 9 | （可选）`src/composables/useRequest.ts` | 新建 | 无 |

### 7.2 学生端 `idfrontend`（**同步改造**）

| # | 文件 | 改动 | 风险 |
|---|---|---|---|
| 10 | `src/common/utils/http.ts` | 同 #1 | 低 |
| 11 | `src/stores/loading.ts` | 新建 | 无 |
| 12 | `src/components/GlobalProgress.vue` | 新建（用 `el-progress`） | 无 |
| 13 | `src/App.vue` 或顶层 layout | 挂载 `<GlobalProgress />` | 低 |
| 14 | `src/views/template/index.vue` | 删除 `ElMessage.error`；detail 弹窗加 `v-loading` | 低 |
| 15 | （可选）`src/composables/useRequest.ts` | 新建 | 无 |

**学生端细节注意**：
- 学生端 `src/utils/http.ts` 当前是 `export { default } from '@common/utils/http'` 的 re-export，确保 `@common` alias 指向 `idfrontend/src/common`（而非管理端的 `idfrontend-admin/src/common`）
- 检查学生端 `vite.config.ts` 的 alias 配置，避免解析到错误目录

### 7.3 验证两端一致

实施完毕后跑：

```bash
diff idfrontend-admin/src/common/utils/http.ts idfrontend/src/common/utils/http.ts
diff idfrontend-admin/src/stores/loading.ts idfrontend/src/stores/loading.ts
diff idfrontend-admin/src/components/GlobalProgress.vue idfrontend/src/components/GlobalProgress.vue
```

应当完全相同（或仅 import 路径差异）。

---

## 8. 验收标准

- [ ] 全局 progress bar 出现 / 消失时机正确（手动 mock 一个慢请求验证）
- [ ] 并发 3 个请求，progress bar 在第 3 个完成才消失
- [ ] 故意让一个接口 500，控制台只看到 1 次 toast（业务组件不写 ElMessage.error）
- [ ] `silent: true` 配置生效，关闭默认 success toast
- [ ] 详情弹窗点击立即打开 + 骨架屏过渡
- [ ] `grep -r "ElMessage.error" idfrontend-admin/src/views idfrontend/src/views` 命中数大幅减少
- [ ] 管理端与学生端 `http.ts`、`loading.ts`、`GlobalProgress.vue` 内容一致（除 import 路径）

---

## 9. 待评审问题

1. **`silent` 配置是否必要？** 还是直接保留拦截器弹成功消息的现状？ — **倾向引入**
2. **失败时弹窗是否自动关闭？** 默认不关，需要 catch 里手动 `detailDialogVisible = false` 时再说 — **倾向不关**
3. **`useRequest` composable 引入？** 还是先保持 `try/finally` 模板 — **倾向引入**
4. **学生端是否同步改造？** 还是先管理端验证稳定后再平移 — **已决定：同步改造**
5. **进度条样式**：是 Element Plus 的 `el-progress` 还是自绘 3px bar？ — **已决定：用 `el-progress` indeterminate**