# Step 5 · Frontend UI complete diagram and code

> 本步目标：实现前端浮窗组件（ChatBubble）、候选列表卡片（SuggestionsCard）、TemplateApplyDialog 集成（支持 agent 预填跳 Step 2）、管理端知识库 CRUD 页面。

---

## 1. 任务清单

| # | 任务 | 文件 | 关键点 |
|---|------|------|--------|
| 5.1 | 网络层扩展 | src/api/components/agent.ts | 新增 interrupt_resolved 事件处理 |
| 5.2 | ChatBubble 组件 | src/views/chat/ChatBubble.vue | 浮窗 UI, SSE token 流, upload, interrupt 渲染 |
| 5.3 | SuggestionsCard 组件 | src/views/chat/SuggestionsCard.vue | 候选模板列表 + radio 选择 |
| 5.4 | Pinia store | src/stores/agent.ts | sessionId, messages, interruptState, result |
| 5.5 | TemplateApplyDialog 扩展 | src/views/template/components/TemplateApplyDialog.vue | prefilledSelections, prefilledTransforms, readyForStep2 |
| 5.6 | 路由挂载 | src/router/index.ts | /chat, /admin/knowledge |
| 5.7 | 管理端 KB 页面 | idfrontend-admin/src/views/knowledge/ | 上传/列表/删除/统计 |

---

## 2. ChatBubble 组件设计

### 2.1 布局

- 底部右下角悬浮按钮（未读角标）
- 点击展开聊天浮窗（宽度 380px, 高度 520px）
- 顶部标题栏 + 最小化/关闭按钮
- 中部消息列表（支持 token 流式渲染）
- 底部输入区：文字输入框 + 附件上传按钮 + 发送按钮

### 2.2 SSE 事件处理

```typescript
// src/views/chat/ChatBubble.vue
agentStreamChat(message, sessionId, file, {
  onToken: (content) => { /* 追加到最后一条 assistant 消息 */ },
  onInterrupt: (question, extra) => {
    if (extra?.type === 'select_template') {
      showSuggestionsCard(extra.suggestions)
    } else if (extra?.type === 'upload_proof') {
      showUploadPrompt(extra.question)
    }
  },
  onResult: (result) => {
    if (result.readyForStep2) {
      // 跳转到 TemplateApplyDialog Step 2
      router.push({ path: '/template', query: { templateId: result.templateId, prefill: JSON.stringify(result.prefilledSelections) } })
    }
    showResultToast(result)
  },
  onSession: (sid) => { sessionId = sid },
  onDone: () => { isStreaming = false },
})
```

---

## 3. SuggestionsCard 组件

用户收到 select_template interrupt 后，渲染候选模板列表：

- 每行：模板名称 + 最高分 + 匹配 rule 名称 + 预估分 + 理由
- Radio 单选 + 确认按钮
- 点击确认 → 调用 agentResumeStream({selectedTemplateId})

---

## 4. TemplateApplyDialog 扩展

```typescript
// props 新增
const props = defineProps<{
  prefilledSelections?: Record<string, number>
  prefilledTransforms?: Record<number, {attributeId: number, inputValue: number}>
  readyForStep2?: boolean
}>()

// watch readyForStep2
watch(() => props.readyForStep2, (v) => {
  if (v && props.prefilledSelections) {
    // 用 prefill 初始化 groupSelections
    for (const [k, v] of Object.entries(props.prefilledSelections)) {
      groupSelections[k] = v
    }
    dialogStep.value = 2  // 直接跳 Step 2
  }
})
```

---

## 5. 管理端知识库页面

路径：idfrontend-admin/src/views/knowledge/KnowledgeManage.vue

功能：
1. 文件列表（sourceFile + chunkCount）
2. 上传文件（拖拽 PDF/DOCX）
3. 删除文件
4. 统计面板（totalFiles / totalChunks）

---

## 6. 验收清单

- [ ] 浮窗能发送消息，token 流式渲染
- [ ] 上传文件后 agent 返回 suggestions
- [ ] 选完模板后跳转到 TemplateApplyDialog Step 2，且 attribute 已预填
- [ ] 管理端能上传政策文件，看到 chunk 数量
