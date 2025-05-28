# app/mapping.py

INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "title": {
                "type": "text",
                "analyzer": "ik_max_word",
                "search_analyzer": "ik_smart",
                "fields": {
                    "suggest": {
                        "type": "completion",
                        "analyzer": "simple",
                        "preserve_separators": True,
                        "preserve_position_increments": True,
                        "max_input_length": 50
                    }
                }
            },
            "main_content": {
                "type": "text",
                "analyzer": "ik_max_word",
                "search_analyzer": "ik_smart",
                "fields": {
                    "suggest": {
                        "type": "completion",
                        "analyzer": "simple",
                        "preserve_separators": True,
                        "preserve_position_increments": True,
                        "max_input_length": 50
                    }
                }
            },
            "url": {
                "type": "keyword"
            },
            "publish_date": {
                "type": "date"
            },
            "content_hash": {
                "type": "keyword"
            }
        }
    },
    "settings": {
        "analysis": {
            "analyzer": {
                "ik_smart": {
                    "type": "custom",
                    "tokenizer": "ik_smart"
                },
                "ik_max_word": {
                    "type": "custom",
                    "tokenizer": "ik_max_word"
                }
            }
        }
    }
} 