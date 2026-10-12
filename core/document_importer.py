# core/document_importer.py
"""
多格式文档导入器
- 支持 TXT / MD / DOCX / DOC 文件
- 支持 URL 网页抓取
- 自动分段，逐段注入 cortex 管道
- 所有依赖均为可选，缺失时优雅降级
"""
from __future__ import annotations

import os
import re
import time
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

class DocumentImporter:
    """文档导入器 —— 将外部知识源注入 MemVine 认知管道"""

    def __init__(self, cortex):
        self.cortex = cortex

    # ── 公开接口 ──

    def import_file(self, path: str, user_id: str = "stranger") -> dict:
        """
        导入单个文件。自动识别格式。
        返回 {"success": bool, "chunks": int, "errors": list}
        """
        if not os.path.exists(path):
            return {"success": False, "chunks": 0, "errors": [f"文件不存在: {path}"]}

        ext = os.path.splitext(path)[1].lower()
        handlers = {
            ".txt": self._read_txt,
            ".md": self._read_txt,
            ".markdown": self._read_txt,
            ".docx": self._read_docx,
            ".doc": self._read_doc,
        }
        handler = handlers.get(ext, self._read_txt)
        try:
            text = handler(path)
        except Exception as e:
            return {"success": False, "chunks": 0, "errors": [f"读取失败: {e}"]}

        if not text or not text.strip():
            return {"success": False, "chunks": 0, "errors": ["文件为空"]}

        return self._feed_to_cortex(text, user_id, source_label=f"📄 {os.path.basename(path)}")

    def import_url(self, url: str, user_id: str = "stranger") -> dict:
        """
        导入网页内容。自动提取正文。
        返回 {"success": bool, "chunks": int, "title": str, "errors": list}
        """
        # 优先尝试 requests + BeautifulSoup（更好的正文提取）
        requests_result = _try_requests_parse(url)
        if requests_result:
            text, title = requests_result
            title = title or url
        else:
            try:
                req = Request(url, headers={"User-Agent": "MemVine/3.0"})
                with urlopen(req, timeout=15) as resp:
                    html = resp.read().decode("utf-8", errors="replace")
            except URLError as e:
                return {"success": False, "chunks": 0, "errors": [f"网络错误: {e}"]}
            except Exception as e:
                return {"success": False, "chunks": 0, "errors": [f"抓取失败: {e}"]}

            parser = _TextExtractor()
            parser.feed(html)
            text = parser.get_text()
            title = parser.get_title() or url

        if not text or len(text.strip()) < 50:
            return {"success": False, "chunks": 0, "errors": ["网页正文过短，可能是动态页面"]}

        result = self._feed_to_cortex(text, user_id, source_label=f"🌐 {title[:40]}")
        result["title"] = title
        return result

    def import_directory(self, dir_path: str, user_id: str = "stranger", recursive: bool = False) -> dict:
        """
        批量导入目录下所有支持的文件。
        返回 {"total": int, "imported": int, "total_chunks": int, "per_file": list}
        """
        supported = {".txt", ".md", ".markdown", ".docx", ".doc"}
        files = []

        if recursive:
            for root, _, filenames in os.walk(dir_path):
                for f in filenames:
                    if os.path.splitext(f)[1].lower() in supported:
                        files.append(os.path.join(root, f))
        else:
            for f in os.listdir(dir_path):
                full = os.path.join(dir_path, f)
                if os.path.isfile(full) and os.path.splitext(f)[1].lower() in supported:
                    files.append(full)

        total = len(files)
        imported = 0
        total_chunks = 0
        per_file = []

        for i, fp in enumerate(files):
            print(f"   [{i+1}/{total}] {os.path.basename(fp)} ...")
            r = self.import_file(fp, user_id)
            per_file.append({"file": fp, **r})
            if r["success"]:
                imported += 1
                total_chunks += r["chunks"]

        return {"total": total, "imported": imported, "total_chunks": total_chunks, "per_file": per_file}

    # ── 内部：LLM 摘要 + 入图 ──

    def _feed_to_cortex(self, text: str, user_id: str, source_label: str) -> dict:
        result = self.cortex.reading_engine.read(text, source_label, user_id=user_id)
        if not result["success"]:
            return {"success": False, "chunks": 0, "errors": ["阅读引擎消化失败"]}

        self.cortex.tick()
        self.cortex.save()

        topics = result.get("topics", [])
        print(f"   📝 摘要: 已消化 {result['chunks']} 个单元，话题: {topics}")
        return {
            "success": True,
            "chunks": result["chunks"],
            "summary": f"已消化 {result['chunks']} 个单元，话题: {topics}",
        }


    def _read_txt(self, path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def _read_docx(self, path: str) -> str:
        try:
            from docx import Document
        except ImportError:
            raise ImportError("需要安装 python-docx: pip install python-docx")

        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)

    def _read_doc(self, path: str) -> str:
        """尝试多种方式读取旧版 .doc"""
        # 优先尝试 python-docx（部分新版 .doc 其实是 docx 格式）
        try:
            return self._read_docx(path)
        except Exception:
            pass

        # 尝试 textract
        try:
            import textract
            return textract.process(path).decode("utf-8", errors="replace")
        except ImportError:
            pass
        except Exception:
            pass

        # 尝试 antiword（命令行工具）
        try:
            import subprocess
            result = subprocess.run(["antiword", path], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout
        except FileNotFoundError:
            pass

        raise ImportError(
            "读取 .doc 需要安装以下之一:\n"
            "  pip install python-docx  (推荐)\n"
            "  pip install textract\n"
            "  apt install antiword (Linux)"
        )


# ── 可选增强：requests + BeautifulSoup ──

def _try_requests_parse(url: str) -> tuple[str, str] | None:
    """尝试用 requests + BeautifulSoup 解析，失败返回 None"""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    try:
        resp = requests.get(url, headers={"User-Agent": "MemVine/3.0"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title = soup.title.string.strip() if soup.title else ""

        for tag in soup(["script", "style", "nav", "footer", "header", "iframe", "noscript"]):
            tag.decompose()

        body = soup.find("body")
        if body:
            text = body.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return ("\n\n".join(lines), title)

    except Exception:
        return None

# ── HTML 正文提取器（纯 stdlib，零依赖） ──

class _TextExtractor(HTMLParser):
    """从 HTML 中提取正文和标题，去除标签和脚本"""

    def __init__(self):
        super().__init__()
        self._text = []
        self._title = ""
        self._in_title = False
        self._skip = False
        self._skip_tags = {"script", "style", "noscript", "iframe", "nav", "footer", "header"}

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if self._skip:
            return
        stripped = data.strip()
        if self._in_title and stripped:
            self._title = stripped
        elif stripped:
            self._text.append(stripped)

    def get_text(self) -> str:
        return "\n\n".join(self._text)

    def get_title(self) -> str:
        return self._title