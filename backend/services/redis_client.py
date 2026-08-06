"""
Redis 连接管理
用于会话缓存、限流、幂等键、任务队列等
"""
import redis.asyncio as redis
from backend.config import REDIS_URL

# 异步 Redis 客户端（连接池模式）
_redis_pool: redis.ConnectionPool | None = None
_redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """获取 Redis 异步客户端（单例）"""
    global _redis_client, _redis_pool
    if _redis_client is None:
        _redis_pool = redis.ConnectionPool.from_url(
            REDIS_URL,
            max_connections=20,
            decode_responses=True,
        )
        _redis_client = redis.Redis(connection_pool=_redis_pool)
    return _redis_client


async def close_redis():
    """关闭 Redis 连接（应用退出时调用）"""
    global _redis_client, _redis_pool
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        _redis_pool = None
