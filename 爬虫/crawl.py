import json
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from pymongo import MongoClient, errors as pymongo_errors
from urllib.parse import urljoin, urlparse, urlunparse
import sys
import logging
from pybloom_live import ScalableBloomFilter
import os
from readability import Document # 使用 readability-lxml
import random
import zlib
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import threading

# 日志配置
logging.basicConfig(
    level=logging.INFO, # 修改日志级别为INFO，减少不必要的输出
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        # 可以考虑添加一个FileHandler来将日志保存到文件
        # logging.FileHandler("crawler.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ---------------------------- MongoDB 配置 ----------------------------
MONGO_HOST = 'localhost'
MONGO_PORT = 27017
# 建议为大规模爬取任务使用新的数据库名或明确的集合前缀
MONGO_DB_NAME = 'nankai_crawler_db'
MONGO_COLLECTION_PAGES = 'webpages'        # 存储解析后的页面数据
MONGO_COLLECTION_QUEUE = 'crawl_queue'     # 存储待爬取URL
MONGO_COLLECTION_FAILED = 'failed_urls'    # 存储处理失败的URL
MONGO_COLLECTION_STATS = 'crawler_stats'   # 存储爬虫统计信息
SNAPSHOT_COLLECTION = 'web_snapshots'    # 存储原始HTML快照
MONGO_COLLECTION_DOCUMENTS = 'documents'   # 存储发现的文档链接（如PDF, DOC等）

# ---------------------------- 全局爬虫配置 ----------------------------
headers_parameters = {
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
    # User-Agent 会在请求时动态选择
}
# 常见可下载文件后缀列表
download_suffix_list = [
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".rtf", ".txt", ".csv", # 文档
    ".zip", ".rar", ".tar", ".gz", ".bz2", ".7z",                                   # 压缩包
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".svg",                       # 图片
    ".mp3", ".wav", ".aac",                                                        # 音频
    ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv",                                 # 视频
    ".exe", ".msi", ".dmg", ".apk"                                                  # 可执行/安装包
]

crawl_timeout = 10  # 单个URL请求超时时间 (秒)
# crawl_delay_base = 0.1 # 每个请求后的基础延时（秒），主要靠并发和请求耗时控制速率
# crawl_delay_random = 0.2 # 随机额外延时 (0 到 X 秒)

max_pages_to_crawl = 200000  # 目标爬取页面数量
STATS_ID = "nankai_crawler_main_stats" # 统计文档的ID
SAVE_STATS_INTERVAL_COUNT = 200    # 每处理N个页面保存一次统计
SAVE_STATS_INTERVAL_TIME = 120     # 或每N秒保存一次统计 (秒)

MAX_CONCURRENT_TASKS = int(os.environ.get("CRAWLER_MAX_WORKERS", 10)) # 最大并发任务数，可由环境变量配置
URL_FETCH_BATCH_SIZE = MAX_CONCURRENT_TASKS * 2 # 每次从数据库尝试获取的待爬取URL数量的倍数
NEW_URL_BUFFER_FLUSH_SIZE = 500    # 新URL内存缓冲区的最大大小，满了就批量写入数据库
NEW_URL_BUFFER_FLUSH_INTERVAL = 20 # 或每N秒刷新一次新URL缓冲区 (秒)

PROCESSED_PAGES_BUFFER_FLUSH_SIZE = 100 # 处理完成的页面数据内存缓冲区的最大大小
PROCESSED_PAGES_BUFFER_FLUSH_INTERVAL = 20 # 或每N秒刷新一次已处理页面缓冲区 (秒)

REQUEST_RETRIES = 2  # 请求失败时的重试次数
MAX_RAW_HTML_SIZE = 15 * 1024 * 1024  # 限制下载的原始HTML最大大小 (15MB)
MIN_COMPRESS_SIZE = 500 * 1024      # HTML内容超过此大小 (0.5MB) 才进行压缩存储

# ---------------------------- 初始化MongoDB连接 ----------------------------
try:
    # 移除 replicaSet 参数，除非你的 MongoDB 是副本集配置。
    # 增加 connectTimeoutMS 和 socketTimeoutMS 来更好地控制连接和操作的超时。
    client = MongoClient(
        MONGO_HOST,
        MONGO_PORT,
        serverSelectionTimeoutMS=10000, # 10秒服务器选择超时
        connectTimeoutMS=10000,         # 10秒连接超时
        socketTimeoutMS=30000           # 30秒操作超时 (例如，对于慢查询)
    )
    client.admin.command('ping') # 验证连接是否成功
    db = client[MONGO_DB_NAME]
    pages_collection = db[MONGO_COLLECTION_PAGES]
    queue_collection = db[MONGO_COLLECTION_QUEUE]
    failed_collection = db[MONGO_COLLECTION_FAILED]
    stats_collection = db[MONGO_COLLECTION_STATS]
    snapshots_collection = db[SNAPSHOT_COLLECTION]
    documents_collection = db[MONGO_COLLECTION_DOCUMENTS]

    # 创建索引 (background=True 允许在后台创建，不阻塞其他操作)
    pages_collection.create_index("url", unique=True, background=True)
    pages_collection.create_index("crawled_at", background=True)
    # 队列URL也应唯一，防止重复添加。status 和 added_at 用于查询和排序。
    queue_collection.create_index("url", unique=True, background=True)
    queue_collection.create_index([("status", 1), ("added_at", 1)], background=True)
    failed_collection.create_index("url", unique=True, background=True)
    snapshots_collection.create_index([("url", 1), ("snapshot_date", -1)], background=True)
    snapshots_collection.create_index("content_hash", background=True)
    documents_collection.create_index("url", background=True) # 一个文档URL可能被多个页面引用，所以不唯一
    documents_collection.create_index([("source_page", 1), ("file_type", 1)], background=True)
    logger.info(f"MongoDB连接成功 (DB: {MONGO_DB_NAME})，索引已检查/创建。")

except pymongo_errors.ConnectionFailure as e:
    logger.error(f"MongoDB连接失败 (ConnectionFailure): {e}")
    sys.exit(1)
except pymongo_errors.ServerSelectionTimeoutError as e:
    logger.error(f"MongoDB服务器选择超时: {e}")
    sys.exit(1)
except pymongo_errors.PyMongoError as e:
    logger.error(f"MongoDB初始化时发生其他错误: {e}")
    sys.exit(1)

# ---------------------------- 布隆过滤器初始化 ----------------------------
# 预估容量可以大一些，例如目标页面数的2-5倍，错误率可以低一些
bloom_filter_capacity = max_pages_to_crawl * 3
bloom_filter_error_rate = 0.0001
bloom_filter = ScalableBloomFilter(
    initial_capacity=bloom_filter_capacity,
    error_rate=bloom_filter_error_rate,
    mode=ScalableBloomFilter.SMALL_SET_GROWTH # 或者 LARGE_SET_GROWTH，取决于URL增长模式
)
bloom_filter_lock = threading.Lock() # 布隆过滤器需要线程安全访问

# ---------------------------- 线程安全缓冲区和锁 ----------------------------
new_urls_buffer = set() # 使用set自动去重内存中的新URL
new_urls_buffer_lock = threading.Lock()

processed_pages_buffer = [] # 存储 (page_data, snapshot_data) 元组
processed_pages_buffer_lock = threading.Lock()

# ---------------------------- 辅助函数：加载布隆过滤器 ----------------------------
def load_bloom_filter_from_db():
    logger.info("开始从数据库加载URL到布隆过滤器...")
    loaded_count = 0
    # 优先从已爬取的 pages_collection 加载
    try:
        for doc in pages_collection.find({}, {"url": 1}, no_cursor_timeout=True, batch_size=5000):
            with bloom_filter_lock:
                bloom_filter.add(doc["url"])
            loaded_count +=1
            if loaded_count % 20000 == 0:
                logger.info(f"已加载 {loaded_count} 个URL到布隆过滤器 (来自 pages_collection)...")
        logger.info(f"从 pages_collection 加载完成，共 {loaded_count} 个URL。")

        # 再从待爬取队列 queue_collection 加载 (可选，如果队列很大且包含很多已在pages中的URL)
        # queue_loaded_count = 0
        # for doc in queue_collection.find({}, {"url": 1}, no_cursor_timeout=True, batch_size=5000):
        #     with bloom_filter_lock:
        #         if doc["url"] not in bloom_filter: # 避免重复添加（理论上不应发生太多）
        #             bloom_filter.add(doc["url"])
        #     queue_loaded_count +=1
        #     if queue_loaded_count % 20000 == 0:
        #         logger.info(f"已加载 {queue_loaded_count} 个URL到布隆过滤器 (来自 queue_collection)...")
        # logger.info(f"从 queue_collection 加载完成，共 {queue_loaded_count} 个新URL。")
        # loaded_count += queue_loaded_count

    except pymongo_errors.PyMongoError as e:
        logger.error(f"从数据库加载URL到布隆过滤器时发生错误: {e}")
    except Exception as e:
        logger.error(f"加载布隆过滤器时发生未知异常: {e}")
    logger.info(f"布隆过滤器加载完成。总共加载约 {loaded_count} 个URL (主要来自pages)。当前容量: {len(bloom_filter)}")

# ---------------------------- User-Agent 池 ----------------------------
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.82 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.82 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.82 Mobile Safari/537.36'
    # 可以添加更多User-Agent
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

# ---------------------------- 核心爬取与解析函数 ----------------------------
session_pool = threading.local() # 每个线程使用自己的requests.Session

def get_session():
    if not hasattr(session_pool, "session"):
        session_pool.session = requests.Session()
    return session_pool.session

def clean_text_content(text):
    """深度清理文本，移除不可见字符和多余空白"""
    if not text:
        return ""
    # 移除XML声明和处理指令
    text = re.sub(r'^<\?xml[^>]*\?>', '', text)
    text = re.sub(r'<!DOCTYPE[^>]*>', '', text, flags=re.IGNORECASE)
    # HTML实体解码
    text = html.unescape(text)
    # 移除HTML注释
    text = re.sub(r"", "", text, flags=re.DOTALL)
    # 移除脚本和样式内容 (如果Readability未完全清除)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # BeautifulSoup提取纯文本 (再次确保)
    soup = BeautifulSoup(text, "lxml") # 使用lxml解析器
    text = soup.get_text(separator=" ", strip=True)
    # 过滤控制字符 (除常见空白符如\t, \n, \r) 和其他非打印Unicode字符
    # 保留中文、英文、数字、常见标点和基本空白
    text = re.sub(r'[^\x20-\x7E\u00A0-\uD7FF\uE000-\uFFFD\u4E00-\u9FFF\u3000-\u303F\uff00-\uffef\t\n\r]', '', text)
    # 合并连续空白字符 (包括空格、制表符、换行符等) 为单个空格
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_html_content(url):
    """获取指定URL的HTML原始内容"""
    thread_session = get_session()
    current_headers = headers_parameters.copy()
    current_headers['User-Agent'] = get_random_user_agent()

    for attempt in range(REQUEST_RETRIES + 1): # 包括初次尝试
        try:
            with thread_session.get(
                url,
                headers=current_headers,
                timeout=crawl_timeout,
                allow_redirects=True,
                stream=True # 启用流式下载以检查Content-Type和大小
            ) as response:
                response.raise_for_status() # 对4xx/5xx错误抛出HTTPError

                content_type = response.headers.get('Content-Type', '').lower()
                if 'text/html' not in content_type and 'application/xhtml+xml' not in content_type:
                    logger.info(f"跳过非HTML内容: {url} (Content-Type: {content_type})")
                    return "" # 返回空字符串表示非HTML，但请求成功

                # 检查内容大小限制 (Content-Length)
                content_length_str = response.headers.get('Content-Length')
                if content_length_str:
                    try:
                        content_length = int(content_length_str)
                        if content_length > MAX_RAW_HTML_SIZE:
                            logger.warning(f"内容过大 (Content-Length: {content_length} bytes)，跳过: {url}")
                            record_failed_url(url, f"Content too large (Content-Length: {content_length})")
                            return None # 获取失败
                    except ValueError:
                        logger.warning(f"无法解析Content-Length: {content_length_str} for {url}")


                raw_content_bytes = b""
                # 分块读取，并实时检查大小
                for chunk in response.iter_content(chunk_size=8192 * 4): # 32KB per chunk
                    raw_content_bytes += chunk
                    if len(raw_content_bytes) > MAX_RAW_HTML_SIZE:
                        logger.warning(f"下载过程中内容超限 (已下载 {len(raw_content_bytes)} bytes)，跳过: {url}")
                        record_failed_url(url, f"Content too large (Downloaded: {len(raw_content_bytes)})")
                        return None # 获取失败
                
                # 尝试解码 (requests通常能从headers或meta标签中检测编码)
                # 优先使用requests检测到的编码，其次是chardet (如果安装了)，最后是常见编码列表
                decoded_text = None
                encodings_to_try = []
                if response.encoding and response.encoding != 'ISO-8859-1': # requests的默认回退编码通常不准
                    encodings_to_try.append(response.encoding.lower())
                
                # 尝试从HTML meta标签中提取编码 (更可靠)
                # 注意：这里解码可能需要先用一个通用编码（如utf-8 ignore）初步解码少量头部内容
                try:
                    # 尝试用utf-8解码一小部分来查找meta标签
                    head_sample = raw_content_bytes[:2048].decode('utf-8', errors='ignore')
                    meta_charset_match = re.search(r'<meta.*?charset=["\']?([\w-]+)["\']?', head_sample, re.IGNORECASE)
                    if meta_charset_match:
                        meta_encoding = meta_charset_match.group(1).lower()
                        if meta_encoding not in encodings_to_try:
                            encodings_to_try.insert(0, meta_encoding) # 优先使用meta中声明的
                except Exception:
                    pass # 解析meta失败，忽略

                encodings_to_try.extend(['utf-8', 'gb18030', 'gbk', 'gb2312', 'big5']) # 常见中文编码
                # 去重并保持顺序 (Python 3.7+ dict is ordered)
                final_encodings_to_try = list(dict.fromkeys(encodings_to_try))
                
                for enc in final_encodings_to_try:
                    try:
                        decoded_text = raw_content_bytes.decode(enc, errors='strict')
                        # logger.debug(f"成功使用编码 '{enc}' 解码: {url}")
                        break
                    except (UnicodeDecodeError, LookupError): # LookupError for unknown encoding
                        # logger.debug(f"尝试编码 '{enc}' 失败 for: {url}")
                        continue
                
                if decoded_text is None: # 如果所有尝试都失败
                    decoded_text = raw_content_bytes.decode('utf-8', errors='ignore') # 最后回退
                    logger.warning(f"所有编码尝试失败，使用UTF-8 (ignore errors) 回退: {url}")

                # 移除可能导致XML解析问题的非法字符 (在Readability处理前)
                # decoded_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', decoded_text)
                return decoded_text

        except requests.exceptions.Timeout:
            logger.warning(f"请求超时 {url} (尝试 {attempt+1}/{REQUEST_RETRIES+1})")
        except requests.exceptions.TooManyRedirects:
            logger.error(f"太多重定向，放弃: {url}")
            record_failed_url(url, "Too many redirects")
            return None
        except requests.exceptions.RequestException as e:
            # 更具体的网络错误，如DNS解析失败、连接拒绝等
            logger.warning(f"请求失败 {url}: {type(e).__name__} - {str(e)} (尝试 {attempt+1}/{REQUEST_RETRIES+1})")
        except Exception as e: # 其他意外错误，如在stream处理中
            logger.error(f"获取HTML时发生未知错误 {url}: {type(e).__name__} - {str(e)} (尝试 {attempt+1}/{REQUEST_RETRIES+1})")

        if attempt < REQUEST_RETRIES:
            sleep_time = (2 ** attempt) + random.uniform(0, 1) # 指数退避 + 随机抖动
            # logger.debug(f"请求失败，将在 {sleep_time:.2f} 秒后重试: {url}")
            time.sleep(sleep_time)
        else:
            logger.error(f"超过最大重试次数 ({REQUEST_RETRIES})，放弃获取: {url}")
            record_failed_url(url, f"Exceeded {REQUEST_RETRIES} retries.")
    return None # 所有重试均失败


def extract_and_filter_links(html_content, base_url):
    """从HTML内容中提取、清洗和过滤链接"""
    new_valid_urls = []
    # 目标域名正则: nankai.edu.cn 及其所有子域名
    # 例如: www.nankai.edu.cn, news.nankai.edu.cn, sub.dept.nankai.edu.cn
    target_domain_pattern = re.compile(
        r"^https?://([a-z0-9\-]+\.)*nankai\.edu\.cn(/.*)?$",
        re.IGNORECASE
    )

    try:
        # 使用lxml解析器，更快更健壮
        soup = BeautifulSoup(html_content, "lxml")
    except Exception as e: # 如 VeryLargeTextError from lxml
        logger.error(f"BeautifulSoup解析HTML失败 (base_url: {base_url}): {str(e)}")
        return new_valid_urls # 返回空列表

    for anchor_tag in soup.find_all("a", href=True):
        href_value = anchor_tag.get("href", "").strip()

        # 过滤无效或不必要的链接类型
        if not href_value or href_value.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue

        try:
            # 构造绝对URL
            full_url = urljoin(base_url, href_value)
            parsed_url = urlparse(full_url)

            # 规范化URL：
            # 1. scheme 和 netloc 转小写
            # 2. 移除查询参数 (query) 和片段标识 (fragment)
            # 3. 路径中的连续斜杠替换为单个斜杠，并移除末尾斜杠 (除非路径就是"/")
            scheme = parsed_url.scheme.lower()
            netloc = parsed_url.netloc.lower()
            path = re.sub(r"/+", "/", parsed_url.path)
            if path != "/" and path.endswith("/"):
                path = path[:-1]
            if not path: # 如果路径为空（例如 "http://example.com"），则设为 "/"
                path = "/"

            normalized_url = urlunparse((scheme, netloc, path, "", "", ""))

            # 检查 scheme 是否为 http 或 https
            if scheme not in ("http", "https"):
                # logger.debug(f"跳过非HTTP/HTTPS链接: {normalized_url}")
                continue

            # 检查是否属于目标域名
            if not target_domain_pattern.match(normalized_url):
                # logger.debug(f"跳过外链或不符规则的域名: {normalized_url}")
                continue

            # 检查是否为可下载的文件类型链接
            file_extension = os.path.splitext(parsed_url.path)[1].lower()
            if file_extension in download_suffix_list:
                # logger.info(f"发现文件链接，记录到documents: {normalized_url}")
                doc_data = {
                    "url": normalized_url,
                    "source_page": base_url, # 记录来源页面
                    "crawled_at": datetime.now(timezone.utc),
                    "file_type": file_extension,
                    "original_href": href_value # 保存原始href，可选
                }
                try:
                    # 使用 update_one + $addToSet 或 $setOnInsert 来处理可能的重复文件记录
                    # 这里简单地用 upsert，如果需要跟踪所有引用源，则需更复杂逻辑
                    documents_collection.update_one(
                        {"url": doc_data["url"], "source_page": doc_data["source_page"]}, # 避免同一页面多次记录同一文件
                        {"$setOnInsert": doc_data},
                        upsert=True
                    )
                except pymongo_errors.PyMongoError as e:
                    logger.error(f"保存文件链接到documents_collection失败: {normalized_url} - {str(e)}")
                continue # 文件链接不加入主爬取队列

            # 使用布隆过滤器检查URL是否已处理或已在队列中
            # 加锁以保证线程安全
            with bloom_filter_lock:
                if normalized_url in bloom_filter:
                    # logger.debug(f"URL已存在于布隆过滤器，跳过: {normalized_url}")
                    continue
                # 如果是新的，先加入布隆过滤器，再加入待添加列表
                bloom_filter.add(normalized_url)

            new_valid_urls.append(normalized_url)

        except ValueError as ve: # urljoin 或 urlparse 可能因格式错误的href抛出
            logger.warning(f"处理链接时发生ValueError | Base: {base_url}, Href: {href_value} | 错误: {str(ve)}")
        except Exception as e:
            logger.warning(f"处理链接时发生未知异常 | Base: {base_url}, Href: {href_value} | 错误: {type(e).__name__} - {str(e)}")
            
    # if new_valid_urls:
    #     logger.debug(f"从 {base_url} 发现 {len(new_valid_urls)} 个新链接.")
    return new_valid_urls


def process_url_task(current_url, stats_dict_ref):
    """
    完整的单个URL处理流程：下载、解析、提取内容和链接、存入缓冲区。
    Args:
        current_url (str): 当前待处理的URL。
        stats_dict_ref (dict): 对主爬虫统计字典的引用，用于更新计数器。
    """
    stats_dict_ref["total_requests"] += 1
    html_body = fetch_html_content(current_url)

    if html_body is None: # 获取失败 (超时、网络错误等)
        # record_failed_url 已在 fetch_html_content 中调用
        stats_dict_ref["failed_count"] += 1
        return
    elif not html_body: # 获取成功，但内容非HTML (Content-Type不对)
        stats_dict_ref["non_html_count"] = stats_dict_ref.get("non_html_count", 0) + 1
        # 这种情况不算完全失败，但也不计入成功页面数
        return

    try:
        # 使用Readability提取主要内容和标题
        doc = Document(html_body)
        title = doc.title()
        # 获取HTML格式的主要内容摘要，然后转为纯文本
        content_summary_html = doc.summary(html_partial=True)
        main_text_content = clean_text_content(content_summary_html) # 使用深度清理函数
        del doc # 及时释放Readability文档对象

        # 检查标题和内容是否有效 (避免低质量页面)
        if not title or len(title) < 3 or \
           any(kw in title.lower() for kw in ["403", "404", "error", "not found", "forbidden", "访问受限", "无标题文档", "untitled document"]):
            logger.warning(f"页面标题无效或可疑，跳过存储: {current_url} (标题: {title[:60]})")
            stats_dict_ref["invalid_page_count"] = stats_dict_ref.get("invalid_page_count", 0) + 1
            # 仍然尝试提取链接，因为父页面可能是导航页
            discovered_urls = extract_and_filter_links(html_body, current_url)
            if discovered_urls:
                add_list_of_urls_to_global_buffer(discovered_urls)
            return

        if not main_text_content or len(main_text_content) < 50: # 内容过短也可能无效
             logger.info(f"页面主要内容过短，可能无效，跳过存储: {current_url} (内容长度: {len(main_text_content)})")
             stats_dict_ref["invalid_page_count"] = stats_dict_ref.get("invalid_page_count", 0) + 1
             discovered_urls = extract_and_filter_links(html_body, current_url)
             if discovered_urls:
                add_list_of_urls_to_global_buffer(discovered_urls)
             return


        # 计算原始内容哈希，用于去重或版本控制
        # 使用 utf-8, ignore errors 来编码，避免因微小编码问题导致哈希不同
        html_bytes_for_hash = html_body.encode('utf-8', 'ignore')
        current_content_hash = hashlib.sha256(html_bytes_for_hash).hexdigest()

        # (可选) 检查内容是否与上一个快照相同
        # if check_if_content_unchanged(current_url, current_content_hash):
        #     logger.info(f"内容未改变，跳过存储新快照和页面数据: {current_url}")
        #     stats_dict_ref["unchanged_count"] = stats_dict_ref.get("unchanged_count", 0) + 1
        #     # 即使内容未变，也认为成功访问了该URL，并提取链接
        #     stats_dict_ref["success_count"] += 1 # 算作成功访问
        #     discovered_urls = extract_and_filter_links(html_body, current_url)
        #     if discovered_urls:
        #         add_list_of_urls_to_global_buffer(discovered_urls)
        #     return

        # 准备快照数据 (压缩原始HTML)
        is_compressed = False
        if len(html_bytes_for_hash) > MIN_COMPRESS_SIZE:
            compressed_html_bytes = zlib.compress(html_bytes_for_hash)
            is_compressed = True
        else:
            compressed_html_bytes = html_bytes_for_hash # 小文件直接存储UTF-8字节

        snapshot_doc = None
        if len(compressed_html_bytes) <= MAX_RAW_HTML_SIZE: # 再次检查压缩后的大小
            snapshot_doc = {
                "url": current_url,
                "raw_html_content": compressed_html_bytes, # 存储二进制数据
                "is_compressed": is_compressed,
                "snapshot_date": datetime.now(timezone.utc),
                "content_hash": current_content_hash,
                "status_code": 200 # 假设是成功获取的页面
            }
        else:
            logger.warning(f"压缩后HTML仍然过大 ({len(compressed_html_bytes)} bytes)，不存储raw_html: {current_url}")


        # 准备页面主数据
        page_doc = {
            "url": current_url,
            "title": clean_text_content(title), # 标题也清理一下
            "main_content": main_text_content,  # 存储清理后的纯文本
            "crawled_at": datetime.now(timezone.utc),
            "content_hash": current_content_hash, # 方便快速比较页面内容是否变化
            "snapshot_taken": bool(snapshot_doc) # 标记是否有快照
        }

        # 将处理好的数据放入待批量插入的缓冲区
        with processed_pages_buffer_lock:
            processed_pages_buffer.append((page_doc, snapshot_doc))
        
        stats_dict_ref["success_count"] += 1
        # logger.info(f"成功处理并缓存页面: {current_url}")

        # 从当前页面提取新链接并加入全局新URL缓冲
        discovered_urls = extract_and_filter_links(html_body, current_url)
        if discovered_urls:
            add_list_of_urls_to_global_buffer(discovered_urls)

    except Exception as e:
        stats_dict_ref["failed_count"] += 1
        logger.error(f"处理页面内容或提取链接时出错 {current_url}: {type(e).__name__} - {str(e)}", exc_info=False) # exc_info=True会打印完整堆栈
        record_failed_url(current_url, f"Content processing/link extraction error: {str(e)}")


# ---------------------------- 缓冲区管理函数 ----------------------------
def add_list_of_urls_to_global_buffer(url_list):
    """线程安全地将一批新URL添加到全局待处理URL缓冲区"""
    if not url_list:
        return
    with new_urls_buffer_lock:
        count_before = len(new_urls_buffer)
        new_urls_buffer.update(url_list) # set.update() 自动处理重复
        added_count = len(new_urls_buffer) - count_before
        if added_count > 0:
            logger.debug(f"添加了 {added_count} 个新URL到缓冲区，总大小: {len(new_urls_buffer)}")


def flush_new_urls_from_buffer_to_db_queue():
    """将全局新URL缓冲区的内容批量写入MongoDB的待爬取队列"""
    urls_to_write = []
    with new_urls_buffer_lock:
        if not new_urls_buffer:
            return 0
        urls_to_write = list(new_urls_buffer)
        new_urls_buffer.clear()

    if urls_to_write:
        # logger.info(f"准备将 {len(urls_to_write)} 个URL从缓冲区写入数据库队列...")
        # 构建待插入的文档列表，包含URL、添加时间和初始状态
        url_documents = [
            {"url": u, "added_at": datetime.now(timezone.utc), "status": "pending"}
            for u in urls_to_write
        ]
        try:
            # 使用 insert_many，ordered=False 允许在部分失败（如重复键）时继续插入其余部分
            insert_result = queue_collection.insert_many(url_documents, ordered=False)
            inserted_count = len(insert_result.inserted_ids)
            logger.info(f"成功将 {inserted_count} 个新URL从缓冲区刷新到MongoDB队列。")
            return inserted_count
        except pymongo_errors.BulkWriteError as bwe:
            # BulkWriteError 包含了成功插入的数量和具体的写入错误
            # code 11000 表示重复键错误 (E11000 duplicate key error)
            # 我们主要关心非重复键错误
            num_duplicates = sum(1 for error in bwe.details.get('writeErrors', []) if error.get('code') == 11000)
            num_other_errors = len(bwe.details.get('writeErrors', [])) - num_duplicates
            inserted_via_error = bwe.details.get('nInserted', 0) # 可能有一些通过错误详情报告的插入

            logger.warning(
                f"刷新URL到队列时发生BulkWriteError: "
                f"成功插入(粗略): {inserted_via_error}, "
                f"重复URL数: {num_duplicates}, "
                f"其他写入错误数: {num_other_errors}."
            )
            # 对于非重复键错误，可以考虑记录或重试
            # for error in bwe.details.get('writeErrors', []):
            #     if error.get('code') != 11000:
            #         logger.error(f"非重复键写入错误: {error}")
            return inserted_via_error # 返回一个近似值
        except pymongo_errors.PyMongoError as e:
            logger.error(f"将新URL批量写入MongoDB队列失败: {e}")
            # 考虑失败处理：是否将这些URL重新放回缓冲区？
            # with new_urls_buffer_lock:
            #     new_urls_buffer.update(urls_to_write) # 简单重放回，可能导致循环
    return 0

def flush_processed_pages_from_buffer_to_db():
    """将处理完成的页面数据和快照数据从内存缓冲区批量写入MongoDB"""
    items_to_write = []
    with processed_pages_buffer_lock:
        if not processed_pages_buffer:
            return
        items_to_write = list(processed_pages_buffer) # 复制一份进行处理
        processed_pages_buffer.clear()

    if items_to_write:
        # logger.info(f"准备将 {len(items_to_write)} 组页面/快照数据从缓冲区写入数据库...")
        page_docs_for_db = []
        snapshot_docs_for_db = []

        for page_data, snapshot_data in items_to_write:
            page_docs_for_db.append(page_data)
            if snapshot_data: # 快照可能因为过大等原因未创建 (None)
                snapshot_docs_for_db.append(snapshot_data)
        
        # 使用 bulk_write 进行更精细的批量操作 (upsert for pages, insert for snapshots)
        from pymongo import ReplaceOne, InsertOne
        
        page_operations = []
        if page_docs_for_db:
            # 对 pages_collection 使用 ReplaceOne 实现 upsert 逻辑
            # 即如果URL已存在，则替换整个文档；如果不存在，则插入。
            page_operations = [
                ReplaceOne({"url": doc["url"]}, doc, upsert=True)
                for doc in page_docs_for_db
            ]
        
        snapshot_operations = []
        if snapshot_docs_for_db:
            # 快照通常是追加新的，所以用 InsertOne
            snapshot_operations = [InsertOne(doc) for doc in snapshot_docs_for_db]

        try:
            if page_operations:
                page_result = pages_collection.bulk_write(page_operations, ordered=False)
                logger.info(
                    f"页面数据批量写入: "
                    f"Matched: {page_result.matched_count}, "
                    f"Upserted: {page_result.upserted_count}, "
                    f"Modified: {page_result.modified_count}, "
                    f"Inserted by upsert: {len(page_result.upserted_ids)}"
                )
            if snapshot_operations:
                snapshot_result = snapshots_collection.bulk_write(snapshot_operations, ordered=False)
                logger.info(f"快照数据批量写入: Inserted: {snapshot_result.inserted_count}")
        except pymongo_errors.BulkWriteError as bwe:
            logger.error(f"批量写入页面/快照数据到MongoDB时发生BulkWriteError: {bwe.details}")
            # 进一步分析 bwe.details['writeErrors'] 来确定哪些操作失败
        except pymongo_errors.PyMongoError as e:
            logger.error(f"写入页面/快照数据到MongoDB时发生其他PyMongoError: {e}")
            # 考虑错误处理：是否将这些数据项重新放回缓冲区？ (较复杂)

# ---------------------------- 失败URL记录与统计信息管理 ----------------------------
def record_failed_url(url, error_message):
    """记录处理失败的URL及其错误信息到数据库"""
    try:
        failed_collection.update_one(
            {"url": url},
            {
                "$inc": {"failure_count": 1}, # 记录失败次数
                "$set": {
                    "last_error_message": str(error_message),
                    "last_failed_at": datetime.now(timezone.utc)
                },
                "$setOnInsert": {"first_failed_at": datetime.now(timezone.utc)}
            },
            upsert=True # 如果URL首次失败，则创建新记录
        )
    except pymongo_errors.PyMongoError as e:
        logger.error(f"记录失败URL到MongoDB时出错: {url} - {e}")


def load_crawler_stats():
    """从数据库加载爬虫的统计信息，如果不存在则初始化。"""
    stats_data = stats_collection.find_one({"_id": STATS_ID})
    if stats_data:
        # 确保所有期望的字段都存在，并提供默认值
        stats_data.setdefault("total_requests", 0)
        stats_data.setdefault("success_count", 0) # 成功下载并解析的HTML页面
        stats_data.setdefault("failed_count", 0)  # 获取或处理失败的URL
        stats_data.setdefault("non_html_count", 0) # Content-Type非HTML的URL
        stats_data.setdefault("invalid_page_count", 0) # 内容无效（如标题可疑、内容过短）
        stats_data.setdefault("unchanged_count", 0) # 内容未改变的页面 (如果启用此检查)
        stats_data.setdefault("urls_in_queue", queue_collection.count_documents({"status":"pending"})) # 实时队列数
        stats_data.setdefault("start_time", datetime.now(timezone.utc)) # 如果是新启动，记录开始时间
        return stats_data
    else:
        # 初始化统计文档并插入
        initial_stats = {
            "_id": STATS_ID, "total_requests": 0, "success_count": 0, "failed_count": 0,
            "non_html_count": 0, "invalid_page_count": 0, "unchanged_count": 0,
            "urls_in_queue": queue_collection.count_documents({"status":"pending"}),
            "start_time": datetime.now(timezone.utc),
            "last_updated": datetime.now(timezone.utc)
        }
        try:
            stats_collection.insert_one(initial_stats)
        except pymongo_errors.PyMongoError as e:
            logger.error(f"初始化统计信息失败: {e}")
            # 即使插入失败，也返回一个临时的初始统计字典
        return initial_stats

def save_crawler_stats(current_stats):
    """保存当前统计信息到数据库。"""
    current_stats["last_updated"] = datetime.now(timezone.utc)
    # 实时更新队列中的URL数量
    try:
        current_stats["urls_in_queue"] = queue_collection.count_documents({"status": "pending"})
    except pymongo_errors.PyMongoError as e:
        logger.warning(f"获取队列URL数量时出错: {e}, urls_in_queue可能不准确。")

    try:
        stats_collection.replace_one({"_id": STATS_ID}, current_stats, upsert=True)
        # logger.info(f"统计信息已保存: Success: {current_stats['success_count']}, Failed: {current_stats['failed_count']}, Queue: {current_stats['urls_in_queue']}")
    except pymongo_errors.PyMongoError as e:
        logger.error(f"保存统计信息到数据库失败: {e}")

# ---------------------------- 主爬虫逻辑 (main_crawler) ----------------------------
def main_crawler_loop(seed_urls):
    # 启动时加载布隆过滤器
    load_bloom_filter_from_db()

    crawler_stats = load_crawler_stats() # 加载或初始化统计信息

    if crawler_stats.get("success_count", 0) >= max_pages_to_crawl:
        logger.info(f"已达到最大爬取页面数 ({max_pages_to_crawl})。爬虫任务完成。")
        return

    # 将种子URL加入待爬队列 (如果它们还不在布隆过滤器中)
    initial_urls_added_to_queue = 0
    urls_to_seed_in_db = []
    for s_url in seed_urls:
        # 规范化种子URL
        parsed_s_url = urlparse(s_url)
        clean_s_path = re.sub(r"/+", "/", parsed_s_url.path).rstrip("/") or "/"
        norm_s_url = urlunparse((parsed_s_url.scheme.lower(), parsed_s_url.netloc.lower(), clean_s_path, "", "", ""))

        with bloom_filter_lock:
            if norm_s_url not in bloom_filter:
                bloom_filter.add(norm_s_url)
                urls_to_seed_in_db.append({"url": norm_s_url, "added_at": datetime.now(timezone.utc), "status": "pending"})
            else:
                logger.info(f"种子URL {norm_s_url} 已存在于布隆过滤器，跳过添加至队列。")
    
    if urls_to_seed_in_db:
        try:
            seed_insert_result = queue_collection.insert_many(urls_to_seed_in_db, ordered=False)
            initial_urls_added_to_queue = len(seed_insert_result.inserted_ids)
            logger.info(f"已将 {initial_urls_added_to_queue} 个新的种子URL添加到待爬队列。")
        except pymongo_errors.BulkWriteError as bwe:
            # 主要处理重复键错误
            num_seed_duplicates = sum(1 for error in bwe.details.get('writeErrors', []) if error.get('code') == 11000)
            logger.warning(f"添加种子URL到队列时，有 {num_seed_duplicates} 个URL已存在 (重复键)。")
            initial_urls_added_to_queue = bwe.details.get('nInserted',0)
        except pymongo_errors.PyMongoError as e:
            logger.error(f"添加种子URL到队列时发生数据库错误: {e}")
        
        if initial_urls_added_to_queue > 0:
             crawler_stats = load_crawler_stats() # 重新加载统计，更新队列数

    # 动态确定线程数，不超过设定的MAX_CONCURRENT_TASKS
    # num_worker_threads = min(MAX_CONCURRENT_TASKS, (os.cpu_count() or 1) * 5 + 5) # 例如每个CPU核心5个线程，再加5个
    num_worker_threads = MAX_CONCURRENT_TASKS # 直接使用配置的
    logger.info(f"启动爬虫主循环，使用 {num_worker_threads} 个工作线程...")
    logger.info(f"当前目标: {max_pages_to_crawl} 页面。已成功: {crawler_stats['success_count']}.")


    with ThreadPoolExecutor(max_workers=num_worker_threads, thread_name_prefix="CrawlerWorker") as executor:
        active_futures_map = {} # {future_object: url_being_processed}

        last_stats_save_time = time.monotonic()
        last_new_url_flush_time = time.monotonic()
        last_processed_page_flush_time = time.monotonic()

        try:
            while crawler_stats["success_count"] < max_pages_to_crawl:
                # 1. 填充线程池任务 (从MongoDB队列获取URL)
                #    目标是让活跃任务数接近 num_worker_threads
                num_tasks_to_submit = num_worker_threads - len(active_futures_map)
                
                if num_tasks_to_submit > 0:
                    # 从数据库队列中原子性地获取一批待处理URL
                    # find_one_and_update 比 find + delete 更安全
                    urls_for_processing_docs = []
                    for _ in range(num_tasks_to_submit):
                        # 优先处理较早添加的 (LIFO) 或随机选择，或按特定优先级
                        # sort=[("added_at", 1)] 为 FIFO
                        retrieved_doc = queue_collection.find_one_and_update(
                            {"status": "pending"},
                            {"$set": {"status": "processing", "processing_started_at": datetime.now(timezone.utc)}},
                            sort=[("added_at", 1)] 
                        )
                        if retrieved_doc:
                            urls_for_processing_docs.append(retrieved_doc)
                        else:
                            break # 队列中没有更多 'pending'状态的URL了
                    
                    if urls_for_processing_docs:
                        for doc in urls_for_processing_docs:
                            url_to_crawl = doc["url"]
                            # logger.debug(f"提交URL到线程池进行处理: {url_to_crawl}")
                            future_task = executor.submit(process_url_task, url_to_crawl, crawler_stats)
                            active_futures_map[future_task] = url_to_crawl
                    elif not active_futures_map and not new_urls_buffer: # 队列空，无活跃任务，无缓冲URL
                        logger.info("待爬队列为空，且无活跃任务和新URL缓冲。等待一段时间或结束...")
                        time.sleep(10) # 等待10秒，看是否有新URL通过其他途径加入
                        # 再次检查队列，如果仍然为空，可以认为爬取结束
                        if queue_collection.count_documents({"status":"pending"}) == 0 and \
                           not active_futures_map and not new_urls_buffer:
                            logger.info("确认队列为空，所有任务完成，爬虫结束。")
                            break # 退出主循环

                # 2. 处理已完成的任务 (非阻塞式检查)
                #    使用 as_completed 来获取已完成的future，timeout设为较小值避免阻塞
                #    或者，维护一个future列表，定期迭代检查 future.done()
                
                completed_futures_this_round = []

                # timeout=0.1 使得 as_completed 近似非阻塞，允许循环继续处理其他事务
                try:
                    for future in as_completed(active_futures_map.keys(), timeout=50.0):
                        completed_futures_this_round.append(future)
                        processed_url = active_futures_map.pop(future) # 从活跃任务映射中移除
                        try:
                            future.result() # 获取任务结果，主要是为了捕获在任务中发生的异常
                            # 如果任务成功（由process_url_task内部逻辑判断并更新stats），
                            # 则从MongoDB队列中彻底删除该URL记录或标记为'completed'
                            queue_collection.delete_one({"url": processed_url, "status": "processing"})
                            # logger.debug(f"URL处理完成并从队列删除: {processed_url}")
                        except Exception as exc: # 捕获由 future.result() 抛出的、源自任务内部的异常
                            logger.error(f"线程任务执行时发生严重错误 for URL {processed_url}: {exc}", exc_info=False)
                            crawler_stats["failed_count"] += 1 # 确保在这里也计数
                            record_failed_url(processed_url, f"Task execution error in main loop: {exc}")
                            # 将处理失败的URL状态改回 'pending' (可配置重试次数) 或标记为 'failed_permanent'
                            queue_collection.update_one(
                                {"url": processed_url, "status": "processing"}, #确保只更新我们标记为processing的
                                {"$set": {"status": "pending_retry", "error_details": str(exc)}, "$inc": {"retry_attempts": 1}}
                                # 或者: {"$set": {"status": "failed_after_task_error", ...}}
                            )
                except TimeoutError:
                    pass
                # 3. 定期或按需刷新内存缓冲区到数据库
                current_monotonic_time = time.monotonic()
                # 刷新新URL缓冲
                if (len(new_urls_buffer) >= NEW_URL_BUFFER_FLUSH_SIZE) or \
                   (current_monotonic_time - last_new_url_flush_time >= NEW_URL_BUFFER_FLUSH_INTERVAL and len(new_urls_buffer) > 0):
                    # logger.info(f"触发刷新新URL缓冲区 (大小: {len(new_urls_buffer)})...")
                    num_flushed = flush_new_urls_from_buffer_to_db_queue()
                    if num_flushed > 0: crawler_stats["urls_in_queue"] += num_flushed # 近似更新，准确值由save_stats获取
                    last_new_url_flush_time = current_monotonic_time

                # 刷新已处理页面数据缓冲
                if (len(processed_pages_buffer) >= PROCESSED_PAGES_BUFFER_FLUSH_SIZE) or \
                   (current_monotonic_time - last_processed_page_flush_time >= PROCESSED_PAGES_BUFFER_FLUSH_INTERVAL and len(processed_pages_buffer) > 0):
                    # logger.info(f"触发刷新已处理页面缓冲区 (大小: {len(processed_pages_buffer)})...")
                    flush_processed_pages_from_buffer_to_db()
                    last_processed_page_flush_time = current_monotonic_time
                
                # 4. 定期保存总体统计信息
                if (crawler_stats["total_requests"] > 0 and \
                    (crawler_stats["total_requests"] % SAVE_STATS_INTERVAL_COUNT == 0 or \
                     current_monotonic_time - last_stats_save_time >= SAVE_STATS_INTERVAL_TIME)):
                    save_crawler_stats(crawler_stats)
                    last_stats_save_time = current_monotonic_time
                    logger.info(
                        f"进度: Success: {crawler_stats['success_count']}, "
                        f"Failed: {crawler_stats['failed_count']}, "
                        f"Queue: {crawler_stats['urls_in_queue']}, "
                        f"Total Req: {crawler_stats['total_requests']}"
                    )


                # 5. 短暂休眠，避免主循环过于CPU密集 (如果上面没有IO或等待)
                #    如果任务获取和完成处理很快，这里可以加一个小延时
                if not urls_for_processing_docs and not completed_futures_this_round: # 如果本次循环没做太多事
                    time.sleep(0.1) # 短暂休眠0.1秒

        except KeyboardInterrupt:
            logger.info("捕获到Ctrl+C (KeyboardInterrupt)，正在准备关闭爬虫...")
            # executor.shutdown(wait=True) # 等待当前正在执行的任务完成
            # Python 3.9+ 可以用 cancel_futures=True
            # For older versions, shutdown(wait=True) is the best option.
            # New tasks won't be submitted.
        finally:
            logger.info("爬虫主循环结束或被中断。正在执行最后的清理和状态保存...")
            # 关闭线程池，等待所有正在执行的任务完成
            # executor.shutdown(wait=True) # 如果不在try块内，确保这里执行
            
            # 最后一次刷新所有内存缓冲区
            logger.info("执行最终缓冲区刷新...")
            flush_new_urls_from_buffer_to_db_queue()
            flush_processed_pages_from_buffer_to_db()
            
            # 将仍在处理中的任务标记回pending (可选，取决于是否希望重启后立即重试)
            if active_futures_map:
                logger.info(f"有 {len(active_futures_map)} 个任务在退出时仍标记为processing，将其状态改回pending...")
                urls_to_requeue = list(active_futures_map.values())
                if urls_to_requeue:
                    queue_collection.update_many(
                        {"url": {"$in": urls_to_requeue}, "status": "processing"},
                        {"$set": {"status": "pending", "comment": "Requeued on shutdown"}}
                    )

            save_crawler_stats(crawler_stats) # 保存最终的统计信息
            logger.info(f"爬虫最终状态: Success: {crawler_stats['success_count']}, Failed: {crawler_stats['failed_count']}, Queue: {crawler_stats['urls_in_queue']}")

    logger.info(f"爬虫运行结束!")


if __name__ == "__main__":
    # 加载初始种子URL列表
    seed_urls_list = []
    try:
        # 尝试从 'default_urls.json' 文件加载
        with open("default_urls.json", 'r', encoding='utf-8') as f_urls:
            loaded_urls = json.load(f_urls)
            # 期望的JSON结构: {"initial_urls": ["url1", "url2", ...]} 或直接是 ["url1", "url2", ...]
            if isinstance(loaded_urls, dict):
                seed_urls_list = loaded_urls.get("initial_urls", [])
            elif isinstance(loaded_urls, list):
                seed_urls_list = loaded_urls
            else: # 文件内容格式不符合预期
                logger.warning("default_urls.json 内容格式不正确，将使用代码内定义的默认URL。")
                # seed_urls_list = ["https://www.nankai.edu.cn"] # 后备默认
            
            if not seed_urls_list: # 如果解析后列表为空
                logger.warning("default_urls.json 中未找到有效URL或列表为空，使用代码内默认。")
                # seed_urls_list = ["https://www.nankai.edu.cn"]

    except FileNotFoundError:
        logger.warning("default_urls.json 文件未找到, 将使用代码内定义的默认URL。")
        # seed_urls_list = ["https://www.nankai.edu.cn"]
    except (json.JSONDecodeError, ValueError) as e_json:
        logger.warning(f"解析 default_urls.json 文件失败: {e_json}, 将使用代码内定义的默认URL。")
        # seed_urls_list = ["https://www.nankai.edu.cn"]
    
    # 如果经过文件加载后列表仍为空，则使用硬编码的默认值
    if not seed_urls_list:
        seed_urls_list = ["https://www.nankai.edu.cn"] # 最终的后备

    if not seed_urls_list or not any(s.strip() for s in seed_urls_list): # 再次确认有非空URL
        logger.error("没有提供有效的初始URL种子，爬虫无法启动。请在 default_urls.json 中配置或直接修改代码。")
        sys.exit(1)

    logger.info(f"爬虫将从以下初始URL开始: {seed_urls_list}")

    try:
        main_crawler_loop(seed_urls_list)
    except Exception as e_critical: # 捕获主程序中未被处理的严重错误
        logger.critical(f"爬虫主程序发生未捕获的致命错误，程序被迫终止: {e_critical}", exc_info=True)
    finally:
        # 确保MongoDB客户端连接在程序退出前关闭
        if 'client' in globals() and client:
            try:
                client.close()
                logger.info("MongoDB连接已成功关闭。")
            except Exception as e_close:
                logger.error(f"关闭MongoDB连接时发生错误: {e_close}")
        logger.info("爬虫程序执行完毕，退出。")