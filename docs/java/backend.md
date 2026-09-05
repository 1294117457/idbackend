# 后端 (Java) 重构方案 v0.2

> 对应仓库 `idproject/0idbackend2`(已在 `java` 分支),Spring Boot 3.2 + MyBatis-Plus + MySQL。
> 本次只做三件事:**激活 MySQL 数据源** + **补 2 个缺失业务模块** + **为 M2 阶段引入 Qdrant + Lucene**。

---

## 0. 关键结论

| 维度 | 结论 |
|------|------|
| **可行性** | ✅ Java 工程已经 95% 完成(MySQL 已配置,16 controller + 36 mapper)。 |
| **数据库** | MySQL(已配),需要新建一份 `iddata` 库实例,跟 Python 的 PG 完全隔离。 |
| **数据迁移** | ❌ **不需要**。Python 工程不动;Java 工程从空库开始。 |
| **缺失业务** | 只补 `template_category` + `export`,其余 0idbackend2 已经覆盖。 |
| **AI 中间件** | Java 端引入 Qdrant(独立容器)+ 进程内 Lucene;Python 端的 pgvector 不动。 |
| **工作量** | M1 ≈ 1-2 周,M2 ≈ 2 周;M3(AI Agent)见 [agent.md](./agent.md)。 |

---

## 1. 现实校正:工程已经存在的部分

### 1.1 已有配置(打开 `application.yml` 即可看到)

```yaml
spring:
  datasource:
    url: jdbc:mysql://<host>:3306/iddata?useSSL=false&serverTimezone=Asia/Shanghai
    username: root
    password: zhouchenhui
    driver-class-name: com.mysql.cj.jdbc.Driver
  data:
    redis:
      host: <host>
      port: 6379
      password: zhouchenhui
  mail: 已配(QQ 邮箱 SMTP)
  servlet:
    multipart: max-file-size 50MB
minio:
  endpoint: http://<host>:9000
pagehelper: helper-dialect=mysql  ✅ 已经在用 MySQL 分页方言
```

**重点**:
- Java 工程在仓库层已经完全是 MySQL 体系
- 没有任何 PG / pgvector 痕迹
- 没有任何 mapper XML(纯注解 MyBatis-Plus,36 个 mapper 都是 Java interface)
- `pagehelper: helper-dialect=mysql`,分页用 `pageNum/pageSize`,跟 Python 端已经一致

### 1.2 Java 端 16 个 controller 覆盖情况

| 业务 | Java controller | Python 对应 | 状态 |
|------|----------------|-----------|------|
| 登录/认证 | `LoginController`、`TokenController` | `auth.py` | ✅ |
| 用户管理 | `UserController` | `user.py` | ✅ |
| RBAC(角色/权限) | `RoleController`、`PermissionController`、`UserRoleController` | `role.py`、`permission.py` | ✅ |
| 模板 | `TemplateController` | `template.py` | ✅ |
| 加分申请 | `ApplicationController` | `application.py` | ✅ |
| 证明材料 | `ProofController` | `proof.py` | ✅ |
| 属性/规则 | `AttributeController`、`RuleController` | `attribute.py`、`rule.py` | ✅ |
| 需求 | `DemandTemplateController`、`DemandApplicationController` | (Python 端应该有同等) | ✅ |
| 文件 | `FileController` | `file.py` | ✅ |
| 字段配置 | `FieldConfigController` | `extra_info_field.py` | ⚠️ 可能是子集 |
| 系统配置 | `SystemConfigController` | `system_config.py` | ✅ |
| MCP 工具 | `McpToolsController` | (route + protocol) | ✅ |
| **缺失:模板分类** | ❌ 无独立 controller | `template_category.py` | ❌ |
| **缺失:导出** | ❌ 无 controller | `export.py` | ❌ |
| **缺失:AI 对话** | ❌ | `ai_chat.py` | ⏸️ 进 M2/M3 |
| **缺失:嵌入检索** | ❌ | `embedding.py` | ⏸️ 进 M2/M3 |
| **缺失:算分引擎** | ❌ | `calculation_service.py` | ❌ **跳过(零调用方)** |

---

## 2. M1 任务清单(后端业务完整化)

### M1.1 数据库启动

```bash
# 在新机器/容器上启动 MySQL 8.x(跟 Python 的 PG 实例 **完全分开**)
docker run -d \
  --name iddata-mysql \
  -e MYSQL_ROOT_PASSWORD=rootpass \
  -e MYSQL_DATABASE=iddata \
  -e MYSQL_USER=idapp \
  -e MYSQL_PASSWORD=idapp \
  -p 3306:3306 \
  mysql:8.0 \
  --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
```

**与 Python 的 PG 不冲突**:
- 端口:MySQL 用 3306,PG 用 5432
- 数据:iddata 库 vs Python 的 PG 库,完全独立
- Redis / MinIO:Java 端可建一套独立实例(避免和 Python 共享出 bug 时难排查),或者**复用同一套,只是 bucket/前缀加 `java_`** —— 详见 M1.4

### M1.2 修 application.yml(可直接 inline 替换)

```yaml
server:
  port: 8080

spring:
  datasource:
    url: jdbc:mysql://localhost:3306/iddata?useSSL=false&serverTimezone=Asia/Shanghai&characterEncoding=utf8mb4
    username: idapp
    password: idapp
    driver-class-name: com.mysql.cj.jdbc.Driver
    hikari:
      max-lifetime: 480000
      idle-timeout: 600000
      connection-timeout: 30000
      maximum-pool-size: 10
      minimum-idle: 2

  data:
    redis:
      host: localhost
      port: 6379
      # Java 实例独立 Redis db,避免 key 冲撞
      database: 1
      password: zhouchenhui

  mail:
    # 沿用现有 QQ SMTP 配置
    host: smtp.qq.com
    port: 587

  servlet:
    multipart:
      max-file-size: 50MB

minio:
  endpoint: http://localhost:9000
  access-key: minioadmin
  secret-key: zchzch22
  bucket-name: java-id-bucket    # 不要用 id-bucket(那是 Python 端的)
  avatar-bucket-name: java-avatars
  secure: false

mybatis:
  type-aliases-package: com.zch.idbackend.domain
  configuration:
    log-impl: org.apache.ibatis.logging.stdout.StdOutImpl

pagehelper:
  helper-dialect: mysql
  reasonable: true

ai-agent:
  base-url: http://localhost:3001
```

### M1.3 补 2 个缺失业务模块

#### M1.3.1 TemplateCategoryController

参考 Python `template_category.py` 实现,Java 端新建:

```
controller/businessController/
  TemplateCategoryController.java   # 路由
service/businessService/
  TemplateCategoryService.java      # 业务
service/bo/
  TemplateCategoryBO.java           # 业务对象
mapper/businessMapper/
  TemplateCategoryMapper.java       # MyBatis-Plus 注解
mapper/po/
  TemplateCategoryPO.java           # 数据库实体
```

参考 Python 路由:
- `GET /api/template-category/list` → 树形
- `POST /api/template-category/create`
- `PUT /api/template-category/update`
- `DELETE /api/template-category/delete`

实现要点:
- 树形结构:用 `parent_id` 自引用,启动期一次性 `WHERE deleted=0` 拉全表,然后内存递归构建
- 用 `ResultVo<List<TemplateCategoryVO>>` 包装结果(跟 Java 现有 16 个 controller 的风格一致)

#### M1.3.2 ExportController

参考 Python `export.py` + `export_service.py`:

**难点**:Python 端用 `openpyxl` 做了样式控制(列宽、字体、合并、公式),Java 端要用 **EasyExcel** 实现等价样式。

依赖添加(在 `pom.xml`):
```xml
<dependency>
  <groupId>com.alibaba</groupId>
  <artifactId>easyexcel</artifactId>
  <version>3.3.4</version>
</dependency>
```

接口契约(查 Python 端导出协议再写,不在此文档穷举):
- `POST /api/export/excel` → 二进制流下载
- `POST /api/export/csv` → 二进制流下载

实现要点:
- 用 `@RequestBody Map params` + Service 内构造 schema
- 返回 `ResponseEntity<byte[]>` 或者 `HttpServletResponse OutputStream`
- 不能只 output file 路径,Python 端是流式响应

### M1.4 Redis / MinIO 隔离策略(逻辑隔离,不新建基础设施)

**不需要新建 Redis 或 MinIO 实例**,现有基础设施完全不动。隔离通过逻辑分区实现:

| 资源 | 隔离方式 | 效果 | Python 端 |
|------|---------|------|---------|
| **Redis** | 改 `database: 1`(Python 用 `database: 0`) | key space 完全隔离 | **不动,零影响** |
| **MinIO** | Java 端新建 bucket:`java-id-bucket` + `java-avatars` | 对象路径完全隔离 | **不动,零影响** |

> ⚠️ `application.yml` 里已经把 `database: 1` 写好了。MinIO 端 Java 新建 bucket 时,**不要动已有的 `id-bucket`**,只创建新 bucket 即可。

实施方法:
- `application.yml` 改 `database: 1` 即可(一行配置)
- `MinioUtil` 改 `bucket-name: java-id-bucket` 即可
- 无需新建 Redis/MinIO 服务,无需改 Python 端任何配置

### M1.5 M1 验收

- [ ] `mvn spring-boot:run` 启动,MySQL 表自动建立(MyBatis-Plus)
- [ ] 健康检查 `GET /health` 返回 200
- [ ] 登录接口 + Token 验证接口跑通
- [ ] `/api/template-category/list` 跑通(新建)
- [ ] `/api/export/excel` 返回正确 XLSX(新建)
- [ ] **前端**可以同时访问 Python(AI/Embedding)和 Java(业务),业务不受影响
- [ ] Redis / MinIO 没有出现两个端共享的脏 key

---

## 3. M2 任务清单(向量库 + BM25)

### 3.1 引入 Qdrant(独立容器)

```bash
# Qdrant 是独立服务,不依赖 PG/pgvector
docker run -d \
  --name iddata-qdrant \
  -p 6333:6333 \    # HTTP API
  -p 6334:6334 \    # gRPC API (Java 客户端用)
  -v qdrant-data:/qdrant/storage \
  qdrant/qdrant:latest
```

跟 PG/pgvector **完全无关**:
- Qdrant 自己存储向量 + payload JSON
- 不读 PG 不读 MySQL
- 数据完全独立

**embedding 模型**:用云 API,不走 Python 端 pgvector,零 ETL。

### 3.2 Qdrant Java 客户端

```xml
<!-- pom.xml -->
<dependency>
  <groupId>io.qdrant</groupId>
  <artifactId>qdrant-java</artifactId>
  <version>1.7.0</version>
</dependency>
```

封装类:
```java
// service/vector/QdrantClient.java
@Service
public class QdrantService {
    private final QdrantClient client;

    @Value("${qdrant.host}") private String host;
    @Value("${qdrant.port}") private int port;

    public QdrantService() {
        this.client = new QdrantClient(
            QdrantGrpcClient.newBuilder(host, port, false).build()
        );
    }

    public void upsertEmbedding(String collection, List<Float> vector, Map<String, Object> payload) {
        // ...
    }

    public List<ScoredPoint> searchEmbedding(String collection, List<Float> query, int topK) {
        // ...
    }
}
```

### 3.3 Lucene(进程内 BM25)

**不需要独立容器**,直接用 Maven 依赖:

```xml
<dependency>
  <groupId>org.apache.lucene</groupId>
  <artifactId>lucene-core</artifactId>
  <version>9.10.0</version>
</dependency>
<dependency>
  <groupId>org.apache.lucene</groupId>
  <artifactId>lucene-analysis-smartcn</artifactId>  <!-- 中文分词 -->
  <version>9.10.0</version>
</dependency>
<dependency>
  <groupId>org.apache.lucene</groupId>
  <artifactId>lucene-highlighter</artifactId>
  <version>9.10.0</version>
</dependency>
```

封装:
```java
// service/vector/LuceneBM25Service.java
@Service
public class LuceneBM25Service {
    private Directory indexDir;          // RAMDirectory(单实例足够)
    private IndexWriter writer;
    private static final SmartChineseAnalyzer ANALYZER = new SmartChineseAnalyzer();

    public void buildIndex(List<DocumentText> docs) {
        // 启动期一次性建索引
    }

    public List<ScoreDoc> search(String query, int topK) {
        // 检索
    }
}
```

**为什么内嵌而不是独立服务**:
- 单进程拉一份小语料(模板 / 知识点)很快,10w 文档级别
- 内嵌避免跨进程延迟 + 不需要额外维护
- 跟 Qdrant 协同:在 `EmbeddingService.search()` 里做 RRF fusion

### 3.4 联合检索架构

```
GET /api/embedding/search?q=xxx&top_k=20
      ↓
EmbeddingService.search()
  ├── QdrantVectorSearch.search(q → embedding → topK*4 个 candidates)
  ├── LuceneBM25Service.search(q → topK*4 个 candidates)
  └── RRF fuser.merge(a, b, weight=0.7, 0.3) → topK
      ↓
ResultVo<List<EmbeddingVO>>
```

`q → embedding` 模型:选**云 embedding API**(智谱 Embedding-3 / OpenAI / 火山引擎),Java 端 HTTP 调第三方,**完全不依赖 Python 工程**。这样:
- 无需在 Python 端新增任何代码
- embedding 计算完全解耦
- Java 端代码量极少(一个 HTTP client)

> ⚠️ **不选**:在 Python 工程里新增 FastAPI embedding 子进程 —— 这违反"不动 Python"原则。如果对 embedding 质量要求极高,可以等 M3 阶段 dsh-runtime 引入后统一处理。

### 3.5 M2 验收

- [ ] Qdrant 容器启动,Java 端 upsert 成功
- [ ] Lucene 索引启动期构建完成(`SmartChineseAnalyzer` 中文分词)
- [ ] `/api/embedding/search` 返回 RRF 融合结果
- [ ] 数据 ETL:不需要 ETL(embedding 模型走云 API,Qdrant 存的是文本向量,新建 collection 即可)
- [ ] 前端 embedding 接口可以无缝切到 Java 端(URL 改一下指向 Java,响应体一致)

---

## 4. infra / 安全配置

### 4.1 application.yml 加 qdrant 配置

```yaml
qdrant:
  host: ${QDRANT_HOST:localhost}
  port: ${QDRANT_PORT:6334}    # gRPC 端口
  api-key: ${QDRANT_API_KEY:}  # 可选

embedding:
  # 调本地 Python embedding 服务
  base-url: http://localhost:8001
  timeout-ms: 30000
```

### 4.2 安全策略

**沿用 0idbackend2 现有**:
- `SecurityConfig` + `AuthInterceptor` + `UserContext` ThreadLocal
- `@RequireRole` / `@RequirePermission`
- `JWTUtils` 沿用

**新增**:Java 端生成的 JWT 必须跟 Python 端兼容(同 secret / 同过期),以便跨端鉴权。但**建议初期不强求**,因为前端调 Java 只拿 Java 自己的 token,Java 内部逻辑独立完成。

### 4.3 k6 压测对齐

复用 Python 工程 `tests/k6/test-step1/` 脚本,改 `BASE_URL` 指向 Java:

```bash
k6 run -e BASE_URL=http://localhost:8080 \
       -e TOKEN=<java-token> \
       tests/k6/test-step1/smoke.js
```

对比指标(`http_req_duration`、`http_req_failed`):
- Java 版 P95 < Python 版
- 错误率 < 0.1%
- 第一轮可能 Java 慢(MySQL 还没 warm),跑 5 分钟后会好

---

## 5. 风险清单与对策

| # | 风险 | 影响 | 对策 |
|---|------|------|------|
| B1 | Java/Python 共享 Redis 时 key 冲突 | 低 | 已通过 `database: 1` 隔离,key space 完全不相交 |
| B2 | Java/Python 共享 MinIO 时对象冲突 | 低 | 已通过独立 bucket 隔离,`id-bucket`(Python)和`java-id-bucket`不相交 |
| B3 | MyBatis-Plus 表自动建不能精确复刻 Python 端索引 | 中 | 启动期手动跑 `schema.sql`,不用 `ddl-auto=update` |
| B4 | Qdrant 容器挂了影响 embedding 检索 | 中 | 接口降级:BM25 单独跑也能返回结果 |
| B5 | Lucene 在多实例下数据不一致 | 中 | 单实例设计,后续要做 HA 再换 OpenSearch / Elasticsearch |
| B6 | embedding service 部署在 Python 进程的容器里 | 低 | 用 docker-compose 编排,YAML 模板见 M2 文档附录 |
| B7 | export 模块的 Excel 样式细节差 | 中 | 准备 5 个测试样本(Python 输出一份,Java 输出对比) |
| B8 | 前端分页参数变化(虽然 Python 端 pageNum,但万一前端没及时切换) | 低 | Python 端确实是 pageNum,前端零改;**保险起见,M1 启动后跑 1 次 page 接口确认** |

---

## 6. 时间表

| 周次 | 阶段 | 内容 |
|------|------|------|
| **W1** | M1.1–M1.3 | MySQL 起库 + application.yml 调通 + 16 个 controller 全部跑通 + 新增 template_category |
| **W2** | M1.3–M1.5 | 新增 export + Redis/MinIO 隔离完成 + k6 压测对齐 + Java/前端联调 |
| **W3** | M2.1–M2.4 | Qdrant 容器起 + Java 端 upsert 跑通 + Lucene 索引构建 + 联合检索实现 |
| **W4** | M2.5 + 验收 | Qdrant 容器起 + embedding service 联调 + 切流观察 1 周 |
| **合计** | M1 + M2 | **3 周,1 个 Java 熟手** |

---

## 7. 验收清单(全部 M1 + M2)

- [ ] Java 启动后,MySQL 表全部存在,16 个 controller 都可用
- [ ] template_category / export 两个新 controller 跑通
- [ ] Qdrant upsert 1000 条向量,search top-10 准确率 ≥ 95%
- [ ] Lucene BM25 单独检索可用(降级链路)
- [ ] 联合检索 RRF 融合的 top-10 跟 Python 端 embedding.search() 结果 ≥ 80% 重叠(允许有差异,Java 调优空间大)
- [ ] 数据 ETL:从 Python 的 PG `embeddings` 表全量导入 Qdrant
- [ ] 前端业务接口全部走 Java 端,UI 无报错
- [ ] Java 端 Redis/MinIO 没有 Python 端的 key/对象污染

---

## 8. 下一步行动

1. 你审阅本文档,确认:
   - M1 的"补 template_category + export"是否同意
   - M2 的"Qdrant + Lucene 联合检索"是否同意(还是只想要 Qdrant)
   - 是否同意"embedding 模型调用已有的 Python service"(还是想本地 Java 部署)
2. 我会细化两个新 controller 的接口契约 + MyBatis-Plus Mapper 接口签名草案
3. 在 `0idbackend2` 上开分支 `feature/m1-mysql-business-complete`,开干 M1 任务
4. W1 期间不开 MySQL 库,用 Docker 本地跑临时实例,W2 准备生产实例化

---

## 附录 A:Python 端 vs Java 端分页参数核对

刚 grep 的结果,Python 端**已经在用 pageNum/pageSize**:

| Python 路由 | 参数名 | 备注 |
|------------|--------|------|
| `attribute.py:50-51` | `pageNum/pageSize` | ✅ 已对齐 |
| `rule.py:44-45` | `pageNum/pageSize` | ✅ 已对齐 |
| `template.py:68-69` | `pageNum/pageSize` | ✅ 已对齐 |
| `user.py:114-115` | `pageNum/pageSize` | ✅ 已对齐 |
| `template_category.py:133-134` | `pageNum/pageSize` | ✅ 已对齐 |
| `extra_info_field.py:115-116` | `pageNum/pageSize` | ✅ 已对齐 |
| `application.py:87-88` | `pageNum/pageSize` | ✅ 已对齐 |
| `file.py:107-108` | `pageNum/pageSize` | ✅ 已对齐 |
| `embedding.py:141-142` | `page_num/page_size` | ⚠️ 用下划线(M2 阶段 Java 端兼容) |
| `ai_chat.py:36-37` | `page_num/page_size` | ⚠️ 用下划线(M3 阶段 Java 端兼容) |

**结论**:M1 阶段所有业务接口前端**零改**。M2/M3 才需要单独处理 `page_num` 路径。

---

## 附录 B:Java 工程 controller 列表

```
controller/
  functionController/
    ApplicationController.java        - 加分申请
    DemandApplicationController.java  - 需求申请
    DemandTemplateController.java     - 需求模板
    FieldConfigController.java        - 字段配置
    FileController.java               - 文件
    LoginController.java              - 登录
    McpToolsController.java           - MCP 工具
    PermissionController.java         - 权限
    ProofController.java              - 证明
    RoleController.java               - 角色
    SystemConfigController.java       - 系统配置
    TemplateController.java           - 模板
    TokenController.java              - Token
    UserController.java               - 用户
    UserRoleController.java           - 用户角色
    AttributeController.java          - 属性
```

加上 M1 新增的:
- `TemplateCategoryController.java`
- `ExportController.java`

= 18 个 controller。
