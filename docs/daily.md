
selectinload避免嵌套全量加载

继承ABC,协议Protocol，super

|super使用场景
|    中间件，继承一个框架中间件，
|        super调用父类的功能方法
|        另外加上自己的代码
|    异常
|        继承Exception，通过super调用基类的init方法报错

|python中的ABC,Protocol
|    python核心就是class Child(Parent)为基础实现继承
|    接口，抽象类也是在继承基础上实现
|    class A(ABC),定义抽象类，后续继承这个类必须实现所有方法
|    class B(Protocol)，定义接口，后续继承这个类，可以

|Storage实现
|    首先这里要有底层s3的适配器，然后有对应工厂比如StorageFactory,
|    然后depends从StorageFactory获取存储实例，
|    然后业务代码中（无论route或者service），直接通过depends注入这个实例就好了

|Depends作用
|    全局单例，测试时mock（暂时不了解），lifespan生命周期管理
|    全局单例，
|        代码中就是比如storage: BaseStorage = Depends(get_storage)这样获取全局单例

|lifesapn生命周期管理
|    redis,存储等实例，在应用启动时最好同步注册，在lifesapn中注册
|    llm等资源适合懒加载，在depends中基于lru_cache获取



minio资源获取问题

```
    富文本中存储图片url,
    如果用预签名会过期，直接获取minio文件会有安全问题
    1.nginx代理，minio单独一个rich-text目录公开可读，这里还是有暴露问题，
    2.BBF,backend for frontend,minio只对后端开放，后端拉去minio,redis缓存，返回给前端
```

```
1.前端部署是没有问题的
2.minio关闭公网访问，只基于docker network让后端服务访问
3.后端新增专门访问minio文件资源给前端的BFF端口
```

Storage 层（基础设施）：
├── upload(key, content)
├── download(key) → bytes           # 后端内部使用
├── delete(key)
├── get_public_url(key)             # 公开路径直链
└── get_presigned_url(key, expiry, as_attachment, filename)  # 私有路径预签名

FileService（应用服务）：
├── 公开文件 → 返回 get_public_url()
└── 私有文件 → 返回 get_presigned_url()


┌─────────────────────────────────────────────────────────────────────────┐
│  1. 编辑阶段（前端）                                                      │
│     用户粘贴/插入图片 → 上传到 /editor/upload → MinIO: editor/temp/{uuid}  │
│     → DOM 插入 <img src="editor://temp/{uuid}.{ext}">                    │
├─────────────────────────────────────────────────────────────────────────┤
│  2. 保存阶段（后端 sign_html）                                            │
│     接收 editor://temp/{uuid} → 移动到 editor/{entity}/{id}/{filename}   │
│     → 替换占位符为 editor://object/{entity}/{id}/{filename}              │
├─────────────────────────────────────────────────────────────────────────┤
│  3. 渲染阶段（后端 sign_html）                                            │
│     editor://object/template/123/uuid.png → 签名 URL                     │
├─────────────────────────────────────────────────────────────────────────┤
│  4. 删除阶段（后端 delete_by_entity）                                       │
│     删除 editor/template/{id}/*                                          │
└─────────────────────────────────────────────────────────────────────────┘