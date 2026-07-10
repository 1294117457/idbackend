
selectinload避免嵌套全量加载

继承ABC,协议Protocol，super

super使用场景
    中间件，继承一个框架中间件，
        super调用父类的功能方法
        另外加上自己的代码
    异常
        继承Exception，通过super调用基类的init方法报错

python中的ABC,Protocol
    python核心就是class Child(Parent)为基础实现继承
    接口，抽象类也是在继承基础上实现
    class A(ABC),定义抽象类，后续继承这个类必须实现所有方法
    class B(Protocol)，定义接口，后续继承这个类，可以

Storage实现
    首先这里要有底层s3的适配器，然后有对应工厂比如StorageFactory,
    然后depends从StorageFactory获取存储实例，
    然后业务代码中（无论route或者service），直接通过depends注入这个实例就好了

Depends作用
    全局单例，测试时mock（暂时不了解），lifespan生命周期管理
    全局单例，
        代码中就是比如storage: BaseStorage = Depends(get_storage)这样获取全局单例

lifesapn生命周期管理
    redis,存储等实例，在应用启动时最好同步注册，在lifesapn中注册
    llm等资源适合懒加载，在depends中基于lru_cache获取

test