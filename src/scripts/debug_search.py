"""快速诊断 embedding 搜索问题。

用法: python -m src.scripts.debug_search
"""
import asyncio
from src.infra.ai.model import embed_text, embed_texts


async def main():
    # 从 0总结.pdf 的第一个 chunk 复制一段
    test_text = "null是主动赋值空值，undefined是为定义"
    
    print("=" * 60)
    print("1. 测试 embed_text (查询用) vs embed_texts (入库用)")
    print("=" * 60)
    
    query_vec = await embed_text(test_text)
    doc_vecs = await embed_texts([test_text])
    doc_vec = doc_vecs[0]
    
    print(f"   query_vec 维度: {len(query_vec)}")
    print(f"   doc_vec   维度: {len(doc_vec)}")
    print(f"   query_vec 前5: {query_vec[:5]}")
    print(f"   doc_vec   前5: {doc_vec[:5]}")
    
    # 计算两者余弦相似度
    import math
    dot = sum(a * b for a, b in zip(query_vec, doc_vec))
    norm_q = math.sqrt(sum(a * a for a in query_vec))
    norm_d = math.sqrt(sum(a * a for a in doc_vec))
    cosine_sim = dot / (norm_q * norm_d) if norm_q and norm_d else 0
    
    print(f"\n   query vs doc 余弦相似度: {cosine_sim:.6f}")
    if cosine_sim < 0.99:
        print("   ⚠️  同文本的 query 和 doc embedding 差距较大！")
        print("   这说明 embed_query 和 embed_documents 返回不同向量")
        print("   对于 BGE-M3 这可能是正常的（query/passage 区分）")
    else:
        print("   ✅ 同文本两种方式的向量几乎一致")
    
    print("\n" + "=" * 60)
    print("2. 检查向量格式 (是否有科学记号)")
    print("=" * 60)
    vec_str = str(query_vec)
    has_scientific = 'e-' in vec_str or 'e+' in vec_str
    print(f"   str(vec) 含科学记号: {has_scientific}")
    if has_scientific:
        import re
        sci_values = re.findall(r'[\d.]+e[+-]\d+', vec_str)
        print(f"   科学记号数量: {len(sci_values)}")
        print(f"   示例: {sci_values[:5]}")
    
    print("\n" + "=" * 60)
    print("3. 测试数据库搜索")
    print("=" * 60)
    
    from src.infra.database import AsyncSessionLocal
    from src.repositories.embedding_repo import EmbeddingRepository
    
    async with AsyncSessionLocal() as db:
        results = await EmbeddingRepository.vector_search(
            db, query_vec, top_k=5
        )
        
        print(f"   返回 {len(results)} 条结果:")
        for i, r in enumerate(results):
            print(f"   [{i+1}] score={r['score']:.4f} | title={r['title'][:30]} | chunk#{r['chunk_index']}")
            print(f"       content: {r['content'][:60]}...")


if __name__ == "__main__":
    asyncio.run(main())
