import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from elasticsearch import Elasticsearch

from readability import Document 

def clean_content(text):
    """移除HTML注释、多余空格和不可见字符"""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)  # 删除HTML注释
    text = re.sub(r"\s+", " ", text)                         # 合并连续空白字符
    text = text.strip()                                      # 去除首尾空格
    return text

def get_html(url):
    # 参数    url: 要解析的网址
    # 功能    获取网址对应的html
    # 返回值   返回url解析得到的url
    print(url)
    try:
        response = requests.get(url, timeout=crawl_timeout, headers=headers_parameters, allow_redirects=False)  # allow_redirects是否允许网址跳转
        response.encoding = response.apparent_encoding  # 设置编码为网页编码，否则容易乱码
    except Exception as e:
        print(e)
        return ""
    html = response.text
    return html


def get_expand_urls(bs, url):
    """严格过滤并生成待爬取链接"""
    urls_expand = []
    domain_pattern = re.compile(r"^https?://([a-z0-9-]+\.)*nankai\.edu\.cn")  # 严格匹配南开大学域名
    
    for item in bs.find_all("a"):
        href = item.get("href")
        if not href:
            continue

        # 处理相对路径
        if not href.startswith(("http://", "https://")):
            if href.startswith("/"):
                href = f"{url.rstrip('/')}{href}"
            else:
                href = f"{url}/{href}"

        # 标准化URL
        href = re.sub(r"#.*$", "", href)  # 移除锚点
        href = href.split("?")[0]         # 移除查询参数

        # 过滤条件
        if (
            not domain_pattern.match(href)                # 非南开大学域名
            or href.lower().endswith(tuple(download_suffix_list))  # 下载链接
            or re.search(r"(javascript|download|#)", href)        # 无效协议
        ):
            continue

        urls_expand.append(href)
    return list(set(urls_expand))  # 去重

def print_json_data(json_data):
    # 参数    json_data: 要打印的数据
    # 功能    打印json_data
    # 返回值   无
    # print("%(timestamp)s %(author)s: %(text)s" % hit["_source"])
    # print("%(X-FileName)s" % hit["_source"])
    print("url: " + json_data["url"])
    print("title: " + json_data["title"])
    content = json_data["content"]
    content = str(content).replace('\n', '')
    content = str(content).replace('\t', '')
    if len(content) > 100:  # 只打印content前100个字符
        print("content: " + content[0: 99] + "...")
    else:
        print("content: " + content)
    print()


# 获得html的内容
def content_handler(bs, url, index):
    """提取并保存网页正文内容"""
    try:
        # 使用readability提取正文
        doc = Document(str(bs))
        summary = doc.summary()
        content_bs = BeautifulSoup(summary, "html.parser")
        content = content_bs.get_text(separator="\n", strip=True)
        content = clean_content(content)
        
        # 提取标题
        title = doc.title() or bs.title.get_text() if bs.title else ""
        title = clean_content(title)

        # 验证标题有效性
        invalid_keywords = ["301", "302", "404", "出错", "Error"]
        if not title or any(keyword in title for keyword in invalid_keywords):
            return False

        # 保存结果
        json_data = {"url": url, "title": title, "content": content}
        print_json_data(json_data)
        with open(os.path.join(dirname, f"{index}.json"), "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False)
        return True

    except Exception as e:
        print(f"Error processing {url}: {str(e)}")
        return False



# 迭代爬虫
def crawl_loop(i, url_count, html_index, urls_target, urls_taken):  # i: 迭代次数  urls: 本次迭代要访问的链接
    # 参数    i: 剩余的迭代次数 url_count: 爬虫次数 html_index: 当前网页的序号 urls_target: 当前迭代的所有爬虫目标网址 urls_taken: 已经爬取过且内容有效的网址
    # 功能    对所有urls_target网址进行爬虫，并在网页中解析出更多的网址作为下一次迭代的urls_target进行迭代爬虫
    # 返回值   迭代: crawl_loop(i - 1, url_count, html_index, urls_expand, urls_taken)
    if i == 0:  # 迭代结束
        print("crawl finish!")
        print("总共爬取了" + url_count.__str__() + "个网址")  #
        print("其中，共爬取到" + html_index.__str__() + "个内容有效的网址")  # 注意初始化时添加了域名备案网站，所以这里是html_index
        with open(os.path.join(dirname + "_urls.json"), 'w', encoding="utf-8") as file:  # encoding和ensure_ascii参数保证编码正确
            json.dump(urls_taken, file, ensure_ascii=False)  # 将urls_taken即访问过的urls保存到本地
            file.close()
        with open(os.path.join(dirname + "_urls_invalid.json"), 'w', encoding="utf-8") as file:
            json.dump(urls_invalid, file, ensure_ascii=False)  # 将urls_invalid即访问过且无效的urls保存到本地
            file.close()
        return
    urls_expand = []
    for url in urls_target:  # 对于每个目标网址
        html = get_html(url)  # 获得网页html
        bs = BeautifulSoup(html, "html.parser")  # 获得bs解析包
        for url_expand in get_expand_urls(bs, url):  # 获得当前网页中包含的所有url_expand拓展网址
            if url_expand not in urls_taken:  # 链接未访问
                if url_expand in urls_invalid:  # 如果链接无效，则跳过
                    continue
                html_expand = get_html(url_expand)
                bs_expand = BeautifulSoup(html_expand, "html.parser")
                url_count += 1
                if not content_handler(bs_expand, url_expand, html_index):  # 如果分析当前html内容无效，则跳过，并添加到urls_invalid，下次遇到这个url则会在上面的if语句中过滤
                    urls_invalid.append(url_expand)
                    continue

                # url未访问且内容有效
                html_index += 1
                urls_expand.append(url_expand)  # 添加到拓展列表
                urls_taken.append(url_expand)  # 添加到已访问列表
                page_rank_digraph.add_node(url_expand)  # 添加page_rank图节点
                page_rank_digraph.add_edge((url, url_expand))  # 新添加的节点肯定不存在相关边，直接添加
            else:  # 链接已访问
                if not page_rank_digraph.has_edge((url, url_expand)):  # 若不存在边，则添加
                    page_rank_digraph.add_edge((url, url_expand))
                else:  # 若存在边，则设置边的权重+1
                    page_rank_digraph.set_edge_weight((url, url_expand),
                                                      page_rank_digraph.edge_weight((url, url_expand)) + 1)

    return crawl_loop(i - 1, url_count, html_index, urls_expand, urls_taken)


headers_parameters = {  # 爬虫用到的header
    'Connection': 'Keep-Alive',
    'Accept': 'text/html',
    'Accept-Language': 'en-US,en;q=0.8,zh-Hans-CN;q=0.5,zh-Hans;q=0.3',
    'Accept-Encoding': 'gzip, deflate',
    'User-Agent': 'Mozilla/6.1 (Windows NT 6.3; WOW64; Trident/7.0; rv:11.0) like Gecko'
}
keys = ["href", "title", "content"]  # es索引构建用到的keys
# 下载后缀
download_suffix_list = ["3gp", "7z", "aac", "ace", "aif", "arj", "asf", "avi", "bin", "bz2", "exe", "gz", "gzip", "img",
                        "iso", "lzh", "m4a", "m4v", "mkv", "mov", "mp3", "mp4", "mpa", "mpe", "mpeg", "mpg", "msi",
                        "msu", "ogg", "ogv", "pdf", "plj", "pps", "ppt", "qt", "r0*", "r1*", "ra", "rar", "rm", "rmvb",
                        "sea", "sit", "sitx", "tar", "tif", "tiff", "wav", "wma", "wmv", "z", "zip", "3gp", "7z", "aac",
                        "ace", "ai", "aif", "alz", "apk", "app", "arc", "arj", "asf", "avi", "bh", "bin", "br",
                        "bundle", "bz", "bz2", "cda", "csv", "dif", "dll", "dmg", "doc", "docx", "egg", "eps", "exe",
                        "flv", "gz", "gzip", "img", "ipa", "iso", "isz", "jar", "kext", "lha", "lz", "lzh", "lzma",
                        "m4a", "m4v", "mdb", "mid", "mkv", "mov", "mp3", "mp4", "mpa", "mpe", "mpeg", "mpg", "msi",
                        "msu", "mui", "ogg", "ogv", "pdf", "pkg", "ppt", "pptx", "psd", "pst", "pub", "qt", "r0*",
                        "r1*", "ra", "rar", "rm", "rmvb", "rtf", "sea", "sit", "sitx", "sldm", "sldx", "tar", "tbz",
                        "tbz2", "tgz", "tif", "tiff", "tlz", "txz", "udf", "vob", "vsd", "vsdm", "vsdx", "vss", "vssm",
                        "vst", "vstm", "vstx", "war", "wav", "wbk", "wim", "wks", "wma", "wmd", "wms", "wmv", "wmz",
                        "wp5", "wpd", "wps", "xls", "xlsx", "xps", "xz", "z", "zip", "zipx", "zpaq", "zstd", "jpg", "png"]

# 参数
dirname = datetime.now().strftime("%Y_%m_%d_%H_%M_%S_optimized")
os.makedirs(dirname, exist_ok=True)
crawl_timeout = 1  # 网页爬虫连接超时时间
crawl_iteration_times = 3  # 爬虫迭代的次数
html_index = 0  # 网页的index
url_count = 0  # 爬取网页的总个数，包括无效的网页
urls_target = []  # 爬虫目标网址
urls_taken = []  # 被访问过的网址
urls_invalid = []  # 无效的网址
urls_taken.append("https://beian.miit.gov.cn")  # 在已访问链接中添加备案系统网址，禁止对其的访问

# 初始化
es = Elasticsearch(hosts=['http://localhost:9200'],http_auth=('elastic', 'yqA2Pfh0') )
with open("default_urls.json") as file:  # 初始化爬虫目标网址
    urls_target = json.load(file)  # urls_target = ["https://www.nankai.edu.cn"]  # 爬虫目标网址
# urls_target = ["http://xxgk.nankai.edu.cn"]  # test

# 进行第0次迭代（初始化迭代）
for url_target in urls_target:  # 对于所有目标网址
    html = get_html(url_target)
    bs = BeautifulSoup(html, "html.parser")
    url_count += 1
    if not content_handler(bs, url_target, html_index):
        continue
    html_index += 1
    urls_taken.append(url_target)  # 添加到已访问列表
  

# 执行爬虫
crawl_loop(crawl_iteration_times, url_count, html_index, urls_target, urls_taken)


