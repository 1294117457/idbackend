template-rule-attribute和application-proof的模型应该没什么问题把
  具体要实现的是template可以一对多绑定对应的rule，rule可以一对多绑定对应的attribute，实现多层级分数的计算和匹配
  然后application可能会有几十上百个证明材料，每个证明材料对应一个分数

其中template有条件匹配和分数换算，
  分数换算可以直接用公式换算，
  条件匹配才需要template-rule-attribute，
  但是我现在的设计是换算公式也算作一个attribute，然后让其绑定到rule上，然后让其绑定到template上，
  你觉得用继承或者适配器的方式来实现怎么样？application只依赖template接口，不管具体template是怎么实现的

不过这里换算公式实际可能有不同区间时多个公式，比如0到60分一个公式，61-100一个分数，

你觉得怎么做合适呢  

2.关于template-rule-attribute

你觉得这里template需要具体其显示区分类别吗，实际只是有不同的计算方式对应到不同的attribute上

是不是可以直接就去除template和rule的类别，然后template_rule表记录template和rule的关系

rule_attribute记录rule和attribute的关系，后续使用时，有什么attribute就显示到对应的template中，

具体就是一个rule会有多个attribute，每个rule就是一个下拉选择框，如果对应attribute是条件匹配类型就直接选择，如果是分数计算类型的，就根据选择框，在右侧显示对应的一个输入框，

这样是不是可以简化template-rule-attribute，职责单一，attribute就是实现不同的分数计算属性，rule用于聚合这些属性，template是最终的聚合根  

这里是不是template保留

  id,name,categoryid,max_score,description,review_count,isactive,create_at,updated_at并加一个sort_order就够了
  input_unit和create_by可以去除简化

然后的rule
  priority改名为sort_order，同步名称,并且去除template_id

attribute中，
  需要code吗，是不是也可以去除，
  然后直接一个name-value,
  value如果是condition类型则是匹配的对应分数，如果是transform则是对应公式，
  description则是必须的，用于描述公式；
  然后必须开闭区间吗，开闭区间是不是也可以由公式调整避免，
  比如0-60的闭区间实际就是1-59,这里的input_min就是最小值1，input_max就是最大值60，
  然后display_order改名sort_order，

最后attribute就只需要，  
  id,name,value,input_min,input_max,sort_order,description,is_active,create_at,updated_at

这里总体类似rbac模式一样用template_rule和rule_attribute绑定template-rule-attribute，还能实现复用，

你觉得呢  



直接给templatecategory增加一个判断是否是叶子节点的字段，默认是null，

当增加了子节点时，改为false

然后当一个templatecategory增加了对应的绑定了template时，将这个字段改为true，

如果时false时提示不能绑定template，如果是true校验不能增加子节点

这样可以减少代码逻辑优化性能吗

你觉得怎么样，



## **is_leaf 的收益重新评估**


| **操作**          | **无 is_leaf**              | **有 is_leaf**             |
| --------------- | -------------------------- | ------------------------- |
| 绑定 template 时校验 | 查 template_category（有无子节点） | 直接读字段，0 额外查询 ✅            |
| 添加子分类时校验（父有子）   | 查 template 表               | 读字段=FALSE，直接放行，0 查询 ✅     |
| 添加子分类时校验（父无子）   | 查 template 表               | 读字段=TRUE，还需查 template 表 ❌ |


---

## Template 模块实施方案

### 一、数据模型（不变，两种类型共用一套结构）

```
ScoreTemplate
  template_type: "CONDITION" | "TRANSFORM"
  template_max_score: 分值上限
  category_id → TemplateCategory（分类归属）

ScoreTemplateRule
  template_id → ScoreTemplate
  priority: 优先级（决定匹配顺序）
  rule_score: CONDITION 类型用（命中后得分）；TRANSFORM 类型为 null（由公式计算）

RuleAttribute
  rule_id → ScoreTemplateRule
  attribute_value: 条件值 或 公式字符串（如 "input * 0.5"）
  input_min / input_max: 数值区间（两种类型均可用）
  input_interval: OPEN | CLOSED（区间边界是否包含）
```

**CONDITION 数据示例：**

```
Template(type=CONDITION, max_score=10)
  Rule(priority=1, rule_score=10)
    Attribute(value="national_award")          # 精确匹配
  Rule(priority=2, rule_score=5)
    Attribute(input_min=85, input_max=100)     # 数值区间匹配
```

**TRANSFORM 数据示例（多区间公式）：**

```
Template(type=TRANSFORM, max_score=30)
  Rule(priority=1, rule_score=null)
    Attribute(input_min=0, input_max=60, value="input * 0.5")
  Rule(priority=2, rule_score=null)
    Attribute(input_min=61, input_max=100, value="30 + (input - 60) * 0.3")
```

---

### 二、策略模式（计算逻辑放 Service 层）

**文件位置：** `src/services/calculation_service.py`

```python
from abc import ABC, abstractmethod

# ===== 策略接口 =====

class ITemplateCalculator(ABC):
    @abstractmethod
    def calculate(self, template, user_input: float) -> float:
        pass


# ===== 条件匹配策略 =====

class ConditionCalculator(ITemplateCalculator):
    """按优先级遍历规则，第一个命中的规则取其 rule_score"""

    def calculate(self, template, user_input: float) -> float:
        for rule in sorted(template.rules, key=lambda r: r.priority):
            if self._rule_matches(rule, user_input):
                return float(rule.rule_score or 0)
        return 0.0

    def _rule_matches(self, rule, user_input) -> bool:
        # 所有 attribute 都满足才算命中（AND 关系）
        return all(self._attr_matches(attr, user_input) for attr in rule.attributes)

    def _attr_matches(self, attr, user_input) -> bool:
        if attr.input_min is not None or attr.input_max is not None:
            return self._in_range(user_input, attr)
        return str(user_input) == attr.attribute_value

    def _in_range(self, value, attr) -> bool:
        lo = attr.input_min is None or value >= attr.input_min
        hi = attr.input_max is None or value <= attr.input_max
        return lo and hi


# ===== 公式换算策略 =====

class TransformCalculator(ITemplateCalculator):
    """按优先级遍历规则，找到 input 所在区间，执行对应公式"""

    def calculate(self, template, user_input: float) -> float:
        for rule in sorted(template.rules, key=lambda r: r.priority):
            for attr in rule.attributes:
                if self._in_range(user_input, attr):
                    return self._eval(attr.attribute_value, user_input)
        return 0.0

    def _in_range(self, value, attr) -> bool:
        lo = attr.input_min is None or value >= attr.input_min
        hi = attr.input_max is None or value <= attr.input_max
        return lo and hi

    def _eval(self, formula: str, input_val: float) -> float:
        # 限制作用域，防止注入
        return eval(formula, {"input": input_val, "__builtins__": {}})


# ===== 注册表（新增计算类型只在此处加一行）=====

class TemplateCalculatorRegistry:
    _calculators = {
        "CONDITION": ConditionCalculator(),
        "TRANSFORM": TransformCalculator(),
    }

    @classmethod
    def get(cls, template_type: str) -> ITemplateCalculator:
        calc = cls._calculators.get(template_type)
        if not calc:
            raise ValueError(f"未知模板类型: {template_type}")
        return calc


# ===== 统一入口（Application 层只调用这里）=====

class ScoreCalculationService:
    @staticmethod
    def calculate(template, user_input: float) -> float:
        calculator = TemplateCalculatorRegistry.get(template.template_type)
        raw_score = calculator.calculate(template, user_input)
        # 统一封顶，由 template.template_max_score 控制
        return min(raw_score, float(template.template_max_score))
```

---

### 三、调用关系

```
application_service.py
    ↓ 提交申请时
    score = ScoreCalculationService.calculate(template, user_input)
    ↓
calculation_service.py → TemplateCalculatorRegistry.get(template_type)
    ↓
ConditionCalculator 或 TransformCalculator
```

`application_service` 只知道 `ScoreCalculationService.calculate(template, input)`，
不关心内部是 CONDITION 还是 TRANSFORM。

---

### 四、文件职责一览

```
src/services/
  template_service.py       # 模板 CRUD：增删改查、规则管理
  calculation_service.py    # 计算策略：ITemplateCalculator + 策略类 + 引擎
  application_service.py    # 申请流程：提交、审批、撤回
```

---

### 五、新增计算类型扩展方式

```python
# 1. 新增策略类
class WeightedCalculator(ITemplateCalculator):
    def calculate(self, template, user_input: float) -> float:
        ...

# 2. 注册（只改这一行）
TemplateCalculatorRegistry._calculators["WEIGHTED"] = WeightedCalculator()

# 3. 数据库 template_type 字段允许新值即可
# 其余代码（application_service、路由层）完全不需要改动
```

