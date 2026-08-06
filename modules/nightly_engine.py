from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import md5
from pathlib import Path
from xml.etree import ElementTree

import requests

from app_config import CACHE_DIR, NIGHTLY_NEWS_LIMIT, NIGHTLY_REQUEST_TIMEOUT


class NightlyEngine:
    GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
    CACHE_TTL_MINUTES = 120
    MACRO_QUERIES = [
        "台股 美股 半導體",
        "戰爭 原油 油價",
        "關稅 晶片 半導體",
        "財報 毛利率 獲利",
    ]
    EVENT_SUFFIX_QUERIES = [
        "重大訊息",
        "法說",
        "財報",
        "毛利率",
        "獲利",
    ]
    POSITIVE_KEYWORDS = {
        "停火": 5,
        "降息": 3,
        "上修": 5,
        "回升": 3,
        "成長": 2,
        "創高": 4,
        "擴產": 3,
        "增產": 3,
        "補貼": 2,
        "合作": 2,
        "接單": 3,
        "訂單": 2,
        "庫藏股": 4,
        "配息": 2,
        "獲利成長": 6,
        "獲利創高": 6,
        "毛利率提升": 6,
        "毛利率改善": 5,
        "樂觀": 2,
    }
    NEGATIVE_KEYWORDS = {
        "戰爭": -7,
        "空襲": -7,
        "關稅": -5,
        "制裁": -5,
        "衰退": -4,
        "升息": -3,
        "通膨": -3,
        "下修": -5,
        "虧損": -7,
        "暴跌": -5,
        "停工": -6,
        "罷工": -4,
        "調查": -4,
        "違約": -8,
        "裁員": -3,
        "爆炸": -6,
        "獲利衰退": -6,
        "毛利率下滑": -6,
        "毛利率下修": -7,
        "不如預期": -4,
        "賣超": -2,
    }
    TAG_KEYWORDS = {
        "戰爭": "戰爭",
        "空襲": "戰爭",
        "油價": "油價",
        "原油": "油價",
        "關稅": "關稅",
        "制裁": "制裁",
        "毛利率": "獲利率",
        "獲利": "獲利",
        "財報": "財報",
        "法說": "法說",
        "半導體": "半導體",
        "AI": "AI",
        "擴產": "擴產",
        "庫藏股": "庫藏股",
        "配息": "股利",
    }

    def __init__(
        self,
        timeout: int = NIGHTLY_REQUEST_TIMEOUT,
        news_limit: int = NIGHTLY_NEWS_LIMIT,
    ):
        self.timeout = timeout
        self.news_limit = news_limit
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            }
        )
        self.cache_dir = Path(CACHE_DIR) / "nightly"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._query_cache: dict[str, list[dict]] = {}
        self._ordered_positive_keywords = sorted(
            self.POSITIVE_KEYWORDS.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        self._ordered_negative_keywords = sorted(
            self.NEGATIVE_KEYWORDS.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )

    def analyze(
        self,
        raw_data: dict[str, dict],
        evaluations: dict[str, dict],
    ) -> tuple[dict, dict[str, dict]]:
        market_overview = self._build_market_overview()
        nightly_signals: dict[str, dict] = {}

        for symbol, evaluation in evaluations.items():
            stock_data = raw_data.get(symbol, {})
            nightly_signals[symbol] = self._build_symbol_signal(
                symbol,
                stock_data,
                evaluation,
                market_overview,
            )

        return market_overview, nightly_signals

    def _build_market_overview(self) -> dict:
        headlines: list[dict] = []
        reasons: list[str] = []
        tags: set[str] = set()
        warnings: list[str] = []
        total_score = 0

        for query in self.MACRO_QUERIES:
            try:
                items = self._fetch_google_news(query, limit=2)
            except Exception as exc:
                warnings.append(f"{query} 新聞抓取失敗：{exc}")
                continue

            for item in items:
                if item["title"] in {
                    headline["title"] for headline in headlines
                }:
                    continue
                headlines.append(item)
                score, hits, found_tags = self._score_text(item["title"])
                total_score += max(-6, min(6, score))
                tags.update(found_tags)
                reasons.extend(hits[:2])

        total_score = max(-15, min(15, total_score))
        market_bias = "中性"
        if total_score >= 5:
            market_bias = "偏多"
        elif total_score <= -5:
            market_bias = "偏空"

        summary = "夜間消息整體偏中性"
        if reasons:
            summary = "；".join(self._unique_items(reasons, limit=3))

        return {
            "market_bias": market_bias,
            "macro_score": total_score,
            "summary": summary,
            "tags": sorted(tags),
            "headlines": headlines[:5],
            "warnings": warnings,
        }

    def _build_symbol_signal(
        self,
        symbol: str,
        stock_data: dict,
        evaluation: dict,
        market_overview: dict,
    ) -> dict:
        stock_name = stock_data.get("info", {}).get("name", symbol)
        warnings: list[str] = []
        headlines: list[dict] = []
        reasons: list[str] = []
        tags: set[str] = set(market_overview.get("tags", []))
        score = 0

        seen_titles: set[str] = set()
        queries = [f"{stock_name} {symbol} 台股"] + [
            f"{stock_name} {symbol} {suffix}"
            for suffix in self.EVENT_SUFFIX_QUERIES
        ]
        for query in queries:
            try:
                for item in self._fetch_google_news(query, limit=2):
                    if item["title"] in seen_titles:
                        continue
                    seen_titles.add(item["title"])
                    headlines.append(item)
            except Exception as exc:
                warnings.append(f"{symbol} 夜間新聞抓取失敗：{exc}")
                break

        for item in headlines:
            headline_score, hits, found_tags = self._score_text(item["title"])
            score += max(-8, min(8, headline_score))
            tags.update(found_tags)
            reasons.extend(hits[:2])

        macro_score = market_overview.get("macro_score", 0)
        if macro_score >= 8:
            score += 3
        elif macro_score >= 4:
            score += 1
        elif macro_score <= -8:
            score -= 3
        elif macro_score <= -4:
            score -= 1

        night_score = max(-20, min(20, score))
        tomorrow_score = max(0, min(100, evaluation["score"] + night_score))

        if night_score >= 6:
            bias = "偏多"
            action = "明早可優先留意"
        elif night_score <= -6:
            bias = "偏空"
            action = "明早先觀望或留意風險"
        else:
            bias = "中性"
            action = "夜間消息偏中性"

        summary_parts = self._unique_items(reasons, limit=3)
        if not summary_parts:
            summary_parts = [
                market_overview.get("summary", "夜間消息偏中性")
            ]

        return {
            "night_score": night_score,
            "night_bias": bias,
            "tomorrow_score": tomorrow_score,
            "night_action": action,
            "event_tags": sorted(tags)[:5],
            "headline_summary": "；".join(summary_parts),
            "headlines": headlines[:3],
            "warnings": warnings,
        }

    def _fetch_google_news(self, query: str, limit: int) -> list[dict]:
        if query in self._query_cache:
            return self._query_cache[query][:limit]

        cache_key = md5(query.encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        cached_items = self._read_cache(cache_path)
        if cached_items is not None:
            self._query_cache[query] = cached_items
            return cached_items[:limit]

        params = {
            "q": query,
            "hl": "zh-TW",
            "gl": "TW",
            "ceid": "TW:zh-Hant",
        }
        response = self.session.get(
            self.GOOGLE_NEWS_RSS,
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        items = self._parse_rss_items(response.text)
        try:
            self._write_cache(cache_path, items)
        except OSError:
            pass
        self._query_cache[query] = items
        return items[:limit]

    @staticmethod
    def _parse_rss_items(raw_xml: str) -> list[dict]:
        root = ElementTree.fromstring(raw_xml)
        items: list[dict] = []
        seen_titles: set[str] = set()

        for item in root.findall(".//item"):
            title = (
                (item.findtext("title") or "")
                .replace(" - Google News", "")
                .strip()
            )
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            items.append(
                {
                    "title": title,
                    "link": (item.findtext("link") or "").strip(),
                    "published": (item.findtext("pubDate") or "").strip(),
                }
            )

        return items

    def _read_cache(self, path: Path) -> list[dict] | None:
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(str(payload["fetched_at"]))
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=UTC)
            else:
                fetched_at = fetched_at.astimezone(UTC)
            items = payload["items"]
            if not isinstance(items, list):
                raise TypeError("cache items must be a list")
        except (
            OSError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            path.unlink(missing_ok=True)
            return None

        if datetime.now(UTC) - fetched_at > timedelta(
            minutes=self.CACHE_TTL_MINUTES
        ):
            return None
        return [item for item in items if isinstance(item, dict)]

    def _write_cache(self, path: Path, items: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "items": items,
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)

    def _score_text(self, text: str) -> tuple[int, list[str], set[str]]:
        score = 0
        reasons: list[str] = []
        tags: set[str] = set()

        for keyword, value in self._ordered_positive_keywords:
            if keyword in text:
                score += value
                reasons.append(f"利多：{keyword}")
        for keyword, value in self._ordered_negative_keywords:
            if keyword in text:
                score += value
                reasons.append(f"利空：{keyword}")
        for keyword, tag in self.TAG_KEYWORDS.items():
            if keyword in text:
                tags.add(tag)

        return score, self._unique_items(reasons, limit=4), tags

    @staticmethod
    def _unique_items(items: list[str], limit: int) -> list[str]:
        unique: list[str] = []
        seen = set()
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
            if len(unique) >= limit:
                break
        return unique
