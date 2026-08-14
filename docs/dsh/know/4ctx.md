## ctx 方法大全

### 一、服务管理

| 方法                         | 作用                           | 举例                                                         |
| :--------------------------- | :----------------------------- | :----------------------------------------------------------- |
| `ctx.provide(name, value)`   | 注册一个服务到全局             | `ctx.provide('theme', themeService)` → 别人可以 `ctx.theme` 访问 |
| `ctx.get(name)`              | 获取一个服务（可能不存在时用） | `const conn = ctx.get('connection')`                         |
| `ctx.inject(deps, callback)` | 等某些服务就绪后再执行         | `ctx.inject(['settings'], (ctx) => { ... })` — settings 加载好了再干活 |

------

### 二、生命周期

| 方法                         | 作用                                     | 举例                                                         |
| :--------------------------- | :--------------------------------------- | :----------------------------------------------------------- |
| `ctx.effect(fn, label)`      | 注册一个可撤销的副作用（卸载时自动清理） | `ctx.effect(() => { const off = listen(); return off }, '描述')` |
| `ctx.plugin(plugin, config)` | 手动加载一个子插件                       | `ctx.plugin(MyPlugin, { key: 'value' })`                     |

------

### 三、事件系统（5 种派发模式）

| 方法                           | 作用                                 | 举例                                            |
| :----------------------------- | :----------------------------------- | :---------------------------------------------- |
| `ctx.on(name, listener)`       | 监听事件                             | `ctx.on('theme/change', (snapshot) => { ... })` |
| `ctx.emit(name, ...args)`      | 发出事件（广播，不等待）             | `ctx.emit('theme/change', snapshot)`            |
| `ctx.parallel(name, ...args)`  | 发出事件（并行等待所有监听者完成）   | `ctx.parallel('session/flush')`                 |
| `ctx.serial(name, ...args)`    | 发出事件（顺序执行，有人返回值就停） | `ctx.serial('agent/turn-stopping', agent)`      |
| `ctx.waterfall(name, ...args)` | 中间件链（每个监听者可改写/拦截）    | `ctx.waterfall('tools/execute', call, next)`    |
| `ctx.bail(name, ...args)`      | 顺序执行，第一个有返回值的就终止     | `ctx.bail('agent/pre-step', messages)`          |

------

### 四、作用域/隔离

| 方法                          | 作用                               | 举例                                            |
| :---------------------------- | :--------------------------------- | :---------------------------------------------- |
| `ctx.extend(meta)`            | 创建子 context（继承所有，可覆盖） | `const child = ctx.extend({ myFlag: true })`    |
| `ctx.isolate(name)`           | 创建隔离作用域（某个服务独立）     | `ctx.isolate('tools')` — 这个子树有自己的工具集 |
| `ctx.intercept(name, config)` | 给某个服务追加配置                 | `ctx.intercept('llm', { model: 'gpt-4' })`      |

------

## 用一个完整场景串起来

假设你写一个"番茄钟"插件，在设置里加一行：

export const inject = ['slots', 'locale']  *// 声明依赖*

export function apply(ctx) {

  *// 1. provide: 注册服务（别人可以 ctx.pomodoro 调用）*

  const timer = new PomodoroTimer()

  ctx.provide('pomodoro', timer)

  *// 2. effect: 注册翻译（卸载时自动清理）*

  ctx.effect(() => ctx.locale.register('pomodoro', { zh, en }), '番茄钟翻译')

  *// 3. on: 监听事件（计时结束时通知）*

  ctx.on('pomodoro/done', () => {

​    console.log('休息一下！')

  })

  *// 4. emit: 发出事件（供其他插件监听）*

  timer.onComplete = () => ctx.emit('pomodoro/done')

  *// 5. slots.inject: 把 UI 挂到设置页*

  ctx.slots.inject('settings.general.item', () =>

​    ctx.slots.register({

​      name: 'settings.general.item',

​      id: 'pomodoro',

​      order: 20,

​      locale: 'pomodoro',

​    }, PomodoroSettingsRow)

  )

}

------

## 总结

ctx 的方法 = Cordis 框架的全部 API

服务：provide / get / inject

生命周期：effect / plugin

事件：on / emit / parallel / serial / waterfall / bail

作用域：extend / isolate / intercept

UI（dsh 扩展）：ctx.slots.inject / ctx.slots.register

核心就这些，所有 226 个包都是用这几个方法组合出来的。