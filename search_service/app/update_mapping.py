# app/update_mapping.py
from es_connector import get_es_client
from mapping import INDEX_MAPPING

def update_index_mapping():
    es = get_es_client()
    index_name = "webpages_index"
    
    try:
        # 检查索引是否存在
        if es.indices.exists(index=index_name):
            # 删除现有索引
            es.indices.delete(index=index_name)
            print(f"已删除现有索引: {index_name}")
        
        # 创建新索引
        es.indices.create(index=index_name, body=INDEX_MAPPING)
        print(f"已创建新索引: {index_name}")
        
        # 重新索引数据
        # 这里需要根据您的数据源来实现
        print("请运行数据索引脚本来重新索引数据")
        
    except Exception as e:
        print(f"更新索引映射失败: {str(e)}")

if __name__ == "__main__":
    update_index_mapping() 