"""
AI新闻抓取工具 - 优化版
优先使用Playwright抓取技术媒体，提高成功率
直接生成最终文章，不保存中间文档
"""
import asyncio
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict

try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


# 技术媒体配置（优先级最高）
TECH_MEDIA = {
    "qbitai": {
        "name": "量子位",
        "url": "https://www.qbitai.com",
        "selectors": ["a[href*='/2026/']", "a[href*='/2025/']", "h2 a", "h3 a"],
        "priority": 1
    },
    "jiqizhixin": {
        "name": "机器之心",
        "url": "https://www.jiqizhixin.com",
        "selectors": ["a[href*='/news/']", "a[href*='/articles/']", ".article-item a"],
        "priority": 1
    },
    "36kr": {
        "name": "36氪",
        "url": "https://36kr.com",
        "selectors": ["a[href*='/p/']", ".article-item a", "h3 a"],
        "priority": 2
    },
    "ithome": {
        "name": "IT之家",
        "url": "https://www.ithome.com",
        "selectors": ["a[href*='/0/']", ".post a", "h2 a"],
        "priority": 2
    },
    "csdn": {
        "name": "CSDN",
        "url": "https://www.csdn.net",
        "selectors": ["a[href*='/article/']", ".blog-list a", "h2 a"],
        "priority": 3
    }
}

# 搜索引擎配置
SEARCH_ENGINES = {
    "baidu": {
        "name": "百度",
        "search_url": "https://www.baidu.com/s?wd=",
        "priority": 1
    },
    "bing": {
        "name": "Bing",
        "search_url": "https://www.bing.com/search?q=",
        "priority": 2
    }
}

# AI关键词
AI_KEYWORDS = ["AI", "人工智能", "大模型", "GPT", "Claude", "ChatGPT", "OpenAI", "Anthropic",
               "LLM", "机器学习", "深度学习", "具身智能", "机器人", "AGI", "模型发布"]


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    url: str
    source: str
    content: Optional[str] = None
    is_hot: bool = False


@dataclass
class ScraperResult:
    """抓取结果"""
    platform: str
    success: bool
    items: List[NewsItem] = field(default_factory=list)
    error: Optional[str] = None


class PlaywrightScraper:
    """Playwright网页抓取器"""

    def __init__(self, timeout: int = 45000):
        self.timeout = timeout
        self.browser = None
        self.playwright = None

    async def start(self):
        """启动浏览器"""
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright未安装")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ]
        )

    async def stop(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def new_page(self):
        """创建新页面"""
        page = await self.browser.new_page()
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        return page

    async def fetch_url(self, url: str, wait_time: int = 4000) -> tuple:
        """获取页面"""
        page = await self.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=self.timeout)
            await page.wait_for_timeout(wait_time)
            return page, True
        except Exception as e:
            await page.close()
            return None, False

    async def extract_articles(self, page, selectors: List[str], base_url: str) -> List[Dict]:
        """提取文章"""
        results = []
        for selector in selectors:
            try:
                elements = await page.locator(selector).all()
                for elem in elements[:25]:
                    try:
                        text = await elem.inner_text()
                        href = await elem.get_attribute("href")
                        if text and len(text.strip()) > 15 and href:
                            # 过滤AI相关
                            is_ai = any(kw.lower() in text.lower() for kw in AI_KEYWORDS)
                            if is_ai:
                                full_url = href if href.startswith("http") else f"{base_url.rstrip('/')}{href}"
                                results.append({
                                    "title": text.strip()[:80],
                                    "url": full_url
                                })
                    except:
                        continue
            except:
                continue
        return results


async def scrape_tech_media(scraper: PlaywrightScraper, media_key: str) -> ScraperResult:
    """抓取单个技术媒体"""
    media = TECH_MEDIA.get(media_key)
    if not media:
        return ScraperResult(platform=media_key, success=False, error="未知媒体")

    items = []
    try:
        print(f"抓取 {media['name']}...")
        page, success = await scraper.fetch_url(media["url"], wait_time=5000)

        if not success or page is None:
            return ScraperResult(platform=media["name"], success=False, error="加载失败")

        articles = await scraper.extract_articles(page, media["selectors"], media["url"])

        for article in articles:
            items.append(NewsItem(
                title=article["title"],
                url=article["url"],
                source=media["name"]
            ))

        await page.close()
        print(f"  {media['name']}: {len(items)} 条")
        return ScraperResult(platform=media["name"], success=True, items=items)

    except Exception as e:
        return ScraperResult(platform=media["name"], success=False, error=str(e))


async def scrape_search_engine(scraper: PlaywrightScraper, engine_key: str, query: str) -> ScraperResult:
    """抓取搜索引擎"""
    engine = SEARCH_ENGINES.get(engine_key)
    if not engine:
        return ScraperResult(platform=engine_key, success=False)

    items = []
    try:
        search_url = f"{engine['search_url']}{query} 最新"
        print(f"搜索 {engine['name']}: {query}")
        page, success = await scraper.fetch_url(search_url, wait_time=4000)

        if not success or page is None:
            return ScraperResult(platform=engine["name"], success=False)

        # 百度
        if engine_key == "baidu":
            containers = await page.locator("div.result, div.c-container").all()
            for container in containers[:10]:
                try:
                    links = await container.locator("a[href]").all()
                    for link in links:
                        href = await link.get_attribute("href")
                        text = await link.inner_text()
                        if text and len(text) > 10 and href and "baidu.com/content" not in href:
                            items.append(NewsItem(
                                title=text.strip()[:80],
                                url=href,
                                source=engine["name"]
                            ))
                            break
                except:
                    continue

        # Bing
        elif engine_key == "bing":
            containers = await page.locator("li.b_algo").all()
            for container in containers[:10]:
                try:
                    link = await container.locator("h2 a").first
                    href = await link.get_attribute("href")
                    text = await link.inner_text()
                    if text and href:
                        items.append(NewsItem(
                            title=text.strip()[:80],
                            url=href,
                            source=engine["name"]
                        ))
                except:
                    continue

        await page.close()
        print(f"  {engine['name']}: {len(items)} 条")
        return ScraperResult(platform=engine["name"], success=True, items=items)

    except Exception as e:
        return ScraperResult(platform=engine["name"], success=False, error=str(e))


async def scrape_all(query: Optional[str] = None) -> Dict:
    """抓取所有来源"""
    results = {
        "query": query,
        "timestamp": datetime.now().isoformat(),
        "sources": []
    }

    scraper = PlaywrightScraper(timeout=45000)

    try:
        await scraper.start()
        print("浏览器启动成功")
    except Exception as e:
        print(f"浏览器启动失败: {e}")
        return results

    try:
        # 优先抓取技术媒体
        print("\n[技术媒体]")
        for media_key in ["qbitai", "jiqizhixin", "36kr", "ithome"]:
            result = await scrape_tech_media(scraper, media_key)
            results["sources"].append(result)

        # 搜索引擎补充
        if query:
            print("\n[搜索引擎]")
            for engine_key in ["baidu", "bing"]:
                result = await scrape_search_engine(scraper, engine_key, query)
                results["sources"].append(result)

    finally:
        await scraper.stop()

    return results


def analyze_hot_topics(data: Dict) -> Dict:
    """分析热点话题"""
    all_items = []
    keyword_count = {}

    for source in data.get("sources", []):
        # 处理字典格式
        items = source.items if hasattr(source, 'items') else source.get("items", [])
        for item in items:
            item_dict = asdict(item) if hasattr(item, '__dataclass_fields__') else item
            all_items.append({
                "title": item_dict.get("title", ""),
                "url": item_dict.get("url", ""),
                "source": item_dict.get("source", "")
            })
            # 统计关键词
            title = item_dict.get("title", "")
            for kw in AI_KEYWORDS:
                if kw.lower() in title.lower():
                    keyword_count[kw] = keyword_count.get(kw, 0) + 1

    # 按关键词热度排序
    hot_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "all_items": all_items,
        "hot_keywords": hot_keywords,
        "total": len(all_items)
    }


def generate_article_content(data: Dict, topic: str = None) -> str:
    """生成文章内容提示"""
    analysis = analyze_hot_topics(data)

    # 确定主题
    if topic:
        main_topic = topic
    elif analysis["hot_keywords"]:
        main_topic = analysis["hot_keywords"][0][0]
    else:
        main_topic = "AI热点"

    # 提取相关文章
    relevant_items = []
    for item in analysis["all_items"]:
        if main_topic.lower() in item["title"].lower() or topic.lower() in item["title"].lower():
            relevant_items.append(item)

    # 取前10条
    sources_list = []
    for item in relevant_items[:10]:
        sources_list.append(f"- [{item['source']}] {item['title']} ({item['url']})")

    sources_text = "\n".join(sources_list) if sources_list else "无具体来源"

    prompt = f"""
根据以下信息，生成一篇适合今日头条发布的AI新闻文章。

主题：{main_topic}

相关内容：
{sources_text}

文章要求：
1. 总分总结构，段落首行缩进两个字符
2. 开头一句话吸引读者，中间2-3段展开，结尾总结趋势
3. 段落不要太碎，合并同类内容
4. 口语化、幽默、接地气，用比喻解释技术
5. 关键数据、重要结论用**粗体**突出
6. 不要emoji、不要小标题
7. 结尾列出参考来源

请直接生成完整文章：
"""

    return prompt


async def main():
    parser = argparse.ArgumentParser(description="AI新闻抓取工具")
    parser.add_argument("query", nargs="?", help="查询主题")
    parser.add_argument("--output", "-o", default="", help="输出文章路径")

    args = parser.parse_args()

    print("=" * 50)
    print("AI新闻抓取工具")
    print("=" * 50)

    # 抓取数据
    data = await scrape_all(args.query)

    # 分析热点
    analysis = analyze_hot_topics(data)
    total = analysis["total"]

    print(f"\n共抓取 {total} 条内容")
    if analysis["hot_keywords"]:
        print(f"热点关键词: {', '.join([k[0] for k in analysis['hot_keywords']])}")

    # 生成文章提示
    prompt = generate_article_content(data, args.query)

    # 保存
    output_dir = Path("ai-reports")
    output_dir.mkdir(exist_ok=True)

    query_name = (args.query or analysis["hot_keywords"][0][0] if analysis["hot_keywords"] else "ai").replace(" ", "-")[:20]
    timestamp = datetime.now().strftime('%Y%m%d')

    # 保存原始数据（供AI参考）
    raw_file = output_dir / f"data-{query_name}-{timestamp}.json"
    serializable_data = {
        "query": data["query"],
        "timestamp": data["timestamp"],
        "sources": [
            {
                "platform": s.platform if hasattr(s, 'platform') else s.get("platform", ""),
                "success": s.success if hasattr(s, 'success') else s.get("success", False),
                "items": [asdict(i) if hasattr(i, '__dataclass_fields__') else i for i in (s.items if hasattr(s, 'items') else s.get("items", []))]
            }
            for s in data["sources"]
        ]
    }
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(serializable_data, f, ensure_ascii=False, indent=2)

    # 保存文章提示
    prompt_file = output_dir / f"prompt-{query_name}-{timestamp}.txt"
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(prompt)

    print(f"\n数据保存: {raw_file}")
    print(f"提示保存: {prompt_file}")
    print("\n请查看提示文件，由AI生成最终文章")


if __name__ == "__main__":
    asyncio.run(main())