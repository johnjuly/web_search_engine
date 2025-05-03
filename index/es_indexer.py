"""
Elasticsearch 索引构建脚本（无时间戳版）
功能：批量导入指定文件夹内的 JSON 文件到 Elasticsearch，移除时间戳相关逻辑
"""

from elasticsearch import Elasticsearch, helpers
import json
import os
import logging
from tqdm import tqdm  # 进度条支持

# 配置参数 ==============================================================
CONFIG = {
    "es_hosts": ["http://localhost:9200"],    # ES 地址
    "index_name": "university_notices",       # 索引名称
    "data_folder": "爬虫/2025_05_02_22_21_16_optimized",                  # JSON 文件目录
    "batch_size": 500,                        # 批量插入批次大小
    "log_file": "es_indexer.log" ,            # 日志文件
    "username": "elastic",
    "password": "oobX44qF"
}

# 初始化日志 =============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(CONFIG['log_file']),
        logging.StreamHandler()
    ]
)

def create_index(es):
    """创建 ES 索引（含中文分词配置）"""
    mapping = {
        "settings": {
            "analysis": {
                "analyzer": {
                    "chinese_analyzer": {
                        "type": "custom",
                        "tokenizer": "ik_max_word",  # IK 中文分词器
                        "filter": ["lowercase"]
                    }
                }
            },
            "number_of_shards": 1,           # 测试环境分片数
            "number_of_replicas": 0           # 生产环境建议至少1个副本
        },
        "mappings": {
            "properties": {
                "url": {
                    "type": "keyword",        # URL 精确匹配
                    "ignore_above": 512      # 超长 URL 截断
                },
                "title": {
                    "type": "text",
                    "analyzer": "chinese_analyzer",  # 中文分词
                    "fields": {
                        "keyword": {"type": "keyword"}  # 保留原始标题
                    }
                },
                "content": {
                    "type": "text",
                    "analyzer": "chinese_analyzer",
                    "term_vector": "with_positions_offsets"  # 支持高亮
                }
            }
        }
    }

    if not es.indices.exists(index=CONFIG['index_name']):
        try:
            es.indices.create(index=CONFIG['index_name'], body=mapping)
            logging.info(f"索引 {CONFIG['index_name']} 创建成功")
        except Exception as e:
            logging.error(f"创建索引失败: {str(e)}")
            raise
    else:
        logging.warning(f"索引 {CONFIG['index_name']} 已存在，跳过创建")

def load_and_index_files(es):
    """加载并索引文件"""
    actions = []
    error_files = []

    # 获取文件列表
    files = [f for f in os.listdir(CONFIG['data_folder']) if f.endswith('.json')]
    if not files:
        logging.error("未找到 JSON 文件！")
        return

    # 处理文件（带进度条）
    with tqdm(total=len(files), desc="处理文件中") as pbar:
        for filename in files:
            file_path = os.path.join(CONFIG['data_folder'], filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    doc = json.load(f)
                    # 构建文档（无时间戳）
                    action = {
                        "_index": CONFIG['index_name'],
                        "_id": doc['url'],  # 使用 URL 作为唯一 ID
                        "_source": {
                            "url": doc['url'],
                            "title": doc['title'],
                            "content": doc['content']
                        }
                    }
                    actions.append(action)

                    # 批量提交
                    if len(actions) >= CONFIG['batch_size']:
                        helpers.bulk(es, actions)
                        actions = []
                        pbar.update(CONFIG['batch_size'])

            except Exception as e:
                error_files.append((filename, str(e)))
                logging.error(f"文件 {filename} 处理失败: {str(e)}")

            pbar.update(1)

        # 提交剩余数据
        if actions:
            helpers.bulk(es, actions)

    # 错误报告
    if error_files:
        logging.warning(f"失败文件数: {len(error_files)}")
        for f, err in error_files:
            logging.warning(f" - {f}: {err}")

if __name__ == "__main__":
    try:
        # 连接 ES
        es = Elasticsearch(
            hosts=CONFIG['es_hosts'],
             basic_auth=(CONFIG['username'], CONFIG['password']),
        request_timeout=30,
        max_retries=3
        )
        if not es.ping():
            raise ConnectionError("无法连接到 Elasticsearch")

        # 执行流程
        create_index(es)
        load_and_index_files(es)
        logging.info("=== 索引构建完成 ===")

    except Exception as e:
        logging.critical(f"程序异常终止: {str(e)}", exc_info=True)