connection
  连接redisclient
rediscache
  封装的redis缓存工具
  实现简单的get,set,delete,isexisted,expire,increase，rate_limit

redisfactory
  redis工厂
  返回对应rediscache


redis
  还是串行，但是是异步并发aio；不是并行；不是串行同步阻塞
  在内存中，性能高

  记住使用redis.aioredis获取redis_client就够了

  后续封装redis_cache