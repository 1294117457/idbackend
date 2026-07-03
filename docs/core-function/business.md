@idproject-2026-07-03_120942-dump.sql这是现有数据结构，其中rbac模块相关功能暂时没什么大问题了 

然后我想开始处理业务逻辑问题，除了现在有挺多代码问题，我想先主要针对对象设计实现进行除了



现在业务核心是针对保研功能开发，
设计了template-rule-attribute的模板-规则-属性的一个可以复用的保研模板
然后user表中用相关字段记录了对应的业务信息，
application和对应的application_proofs是用于学生使用template生成对应的加分申请，
  一个application由一个或多个proof组成，
  application有apply_score用户结合模板最终申请的分数，还有approved_score，对应被通过审核的proof的分值的总和
  每个proof有对应的证明材料和申请的分值，
  每个proof被审核通过后，proof的分值才累加到对应application的approved_score上

然后field_config是还未实现的功能
  具体是想，现在模板有大概分为加分模板和需求模板，这里是一级分类
  加分模板还分为3类，这些分类都是在代码中硬编码了，这是二级分类
  但是我想改为也是可以在管理端配置的，因为可能每年政策都会有所修改，类别和对应分数上限可能也会变化

现在template的组成，
  总的就是一级分类和二级分类是写死的
  和模板换算分数的类型，比如条件匹配和分数换算，这是三级分类
    对应的情况分别是比如获得什么奖项可以匹配多少分
    和对应参加比如劳动教育的劳动学分可以按照公式换算对应的可能二级分类对应类别的分数

然后我想实现对一级分类和二级分类也可以灵活的配置，所以之前引入了filed_config，但是还未实现
  现在同时template的condition和transfer的三级分类是否也能优化呢



也就是说，功能分类实际是个计算引擎，不太可能后续动态增加，没必要归于分类中
然后现有的用途的限制分类可以统一一个分类表，结合parentId形成分类树来使用对吗

同时还有一点，现在相关的业务数据字段也是写死在user表中，这里是不是在有了分类后，可以基于分类再有个业务信息表，这里记录用户数据，并且也是动态记录，比如json格式？，然后同时还记录对应数据绑定的用户和对应分类，进而实现user和用户的业务数据分离，并且模板分类和模板分离；同时业务数据又基于模板分类来生成？
结合之前的rbac的role和user分离，进而实现user，template，template_category,user_businessInfo,role,application这几个核心对象解耦

3
CREATE TABLE student_profiles (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER UNIQUE NOT NULL REFERENCES users(id),
    student_id   VARCHAR(20),    -- 学号
    full_name    VARCHAR(100),
    major        VARCHAR(100),
    grade        INTEGER,
    enrollment_year  INTEGER,
    graduation_year  INTEGER,
    is_confirmed BOOLEAN DEFAULT FALSE
);这个仍保留在user表中，作为用户的基本信息
然后总共有User，TemplateCategory ，Template  ，ScoreData，Application ，这几个对象实现核心业务逻辑

具体一点就是，Template 依赖TemplateCategory ，基于Template实现Application，进而生成ScoreData

后续可以一个接口更新分数，从ScoreData中查询对应user的所有成绩信息进行计算，然后更新到grade中，user还可以增加一个json字段，用来接收不是分数的成绩信息，比如四六级？

后续显示现有哪些分类的模板就从TemplateCategory获取，并且这样也可灵活配置
你觉得怎样



CREATE TABLE score_data (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL,
    category_id   INTEGER NOT NULL,   -- TemplateCategory 的叶子节点
    academic_year INTEGER NOT NULL,
    raw_score     DECIMAL(5,2) DEFAULT 0,  -- 累计原始分
    capped_score  DECIMAL(5,2) DEFAULT 0,  -- 按 category.max_score 封顶后
    source_ids    JSON,                     -- 来源 Application ID 列表
    calculated_at TIMESTAMP,
    UNIQUE (user_id, category_id, academic_year)
);
这个实际就是记录每条成功的申请，
  其中有userid用于绑定用户，
  categoryId用于后续计算分数时匹配对应分类是否有超出分类限制，
  然后一个name和value，对应template的名称和对应获取到的值，如果值是数字，那就是分数类型后续用于计算总的成绩；如果值是string那就是后续不需要计算分数的类型直接前端展示对应的name和value
  然后user字段增加一个score_info,用于接收score_data中处理后的信息
后续具体使用时，
  比如显示用户信息时从user的score_info显示对应信息
  然后要有一个接口手动更新数据，从score_data获取对应数据更新score_info，获取对应userId的所有score_data,并且同类数据进行计算，这里计算除了累加同类数据，还结合template_category中对应分类限制，比如一类的分数不能超出上限，超出后就取上限；然后如果是比如四六级分数的string类型的字段，则是取score_data中最新的数据覆盖不累加

你觉得怎么样



增加一个type会不会过于应编码，不想在score_info进行过多的类型分类，
类型应该在template_category中就定义好，然后基于template生成对应的application，进而生成对应的score_data
这一整条线的类型是不是在template_category中定义好更合适呢



总的来说就是
  templateCategory中定义好了类型和对应的一些限制条件，然后绑定到template中，然后生成对应application，然后审批通过后生成对应的score_data，这个思路是没问题的 了
具体就是
  templatecategory定义这一整条业务线的数据的类型和一些限制
  template就是用于绑定分类和限制，并且可以灵活的配置对应的名称和分数计算方法
  application就是学生基于template，然后上传自己材料生成的申请，用于后续审核
  score_data就是审核通过的零散数据的流水线，后续用于一个接口统一计算然后更新到user.scoreinfo

我这么理解对吗




| **层** | **谁定义**          | **谁使用** |
| ----- | ---------------- | ------- |
| 业务规则  | TemplateCategory | 聚合计算时读取 |
| 计分配置  | Template         | 学生申请时选择 |
| 申请流程  | Application      | 审核员审批   |
| 原始结果  | ScoreData        | 计算接口聚合  |
| 汇总快照  | User.score_info  | 前端展示    |


