"""Telegram Ingestion and NLP Feature Extractor for @kpszsu.

Channel: Повітряні Сили ЗС України (https://t.me/kpszsu)

Guarantees Strict Causal Alignment:
- A message published at time t_msg is strictly excluded from any forecast cutoff t_k < t_msg.
- Point-in-time window aggregation: features at t_k summarize messages in [t_k - W, t_k].
"""

import json
from pathlib import Path
import re
from typing import Optional
import urllib.request
import pandas as pd
import numpy as np


THREAT_PATTERNS = {
    "tg_ballistics": re.compile(r"балістик|балістичн", re.IGNORECASE),
    "tg_shahed": re.compile(r"шахед|бпла|безпілот|дрон", re.IGNORECASE),
    "tg_mig31": re.compile(r"міг-31|міг31|кинджал", re.IGNORECASE),
    "tg_aviation": re.compile(r"тактичн|каб|пуск|авіаці", re.IGNORECASE),
    "tg_missile": re.compile(r"ракет|калібр|х-101|х-59", re.IGNORECASE),
    "tg_region_mention": re.compile(r"київ|київщин|біла церква|бровар", re.IGNORECASE),
}


def fetch_kpszsu_channel_messages(
    cache_path: str = "data/kpszsu_posts.json",
    max_pages: int = 5,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetches recent posts from public Telegram web preview https://t.me/s/kpszsu.

    Uses caching to avoid repeated scraping and network overhead.

    Args:
        cache_path: Path to cached JSON file.
        max_pages: Number of backward pagination pages to fetch.
        force_refresh: If True, bypasses cache and re-scrapes.

    Returns:
        DataFrame with columns ['msg_id', 'published_at', 'text'].
    """
    cache_file = Path(cache_path)
    if cache_file.exists() and not force_refresh:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            df = pd.DataFrame(data)
            if not df.empty:
                df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
                return df.sort_values(by="published_at").reset_index(drop=True)

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    all_messages = []
    seen_ids = set()
    current_url = "https://t.me/s/kpszsu"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    for page_idx in range(max_pages):
        try:
            req = urllib.request.Request(current_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8")

            # Extract message blocks
            # Find widget message divs with data-post attribute
            msg_blocks = re.findall(
                r'<div class="tgme_widget_message[^"]*"\s+data-post="kpszsu/(\d+)"[^>]*>(.*?)</div>\s*<!--',
                html,
                re.DOTALL,
            )

            if not msg_blocks:
                # Fallback: general time & text extraction
                times = re.findall(r'<time[^>]*datetime="([^"]+)"', html)
                texts = re.findall(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
                for i, (t_str, raw_t) in enumerate(zip(times, texts)):
                    clean_t = re.sub(r"<[^>]+>", "", raw_t).strip()
                    all_messages.append({
                        "msg_id": f"page{page_idx}_{i}",
                        "published_at": t_str,
                        "text": clean_t,
                    })
                break

            for post_id, block in msg_blocks:
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                time_match = re.search(r'<time[^>]*datetime="([^"]+)"', block)
                text_match = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)

                if time_match and text_match:
                    t_str = time_match.group(1)
                    raw_text = text_match.group(1)
                    clean_text = re.sub(r"<[^>]+>", "", raw_text).strip()
                    all_messages.append({
                        "msg_id": post_id,
                        "published_at": t_str,
                        "text": clean_text,
                    })

            # Look for previous page link: href="/s/kpszsu?before=..."
            prev_match = re.search(r'href="/s/kpszsu\?before=(\d+)"', html)
            if prev_match:
                before_id = prev_match.group(1)
                current_url = f"https://t.me/s/kpszsu?before={before_id}"
            else:
                break

        except Exception as e:
            print(f"Warning: could not fetch page {page_idx} from Telegram: {e}")
            break

    df = pd.DataFrame(all_messages)
    if not df.empty:
        df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
        df = df.drop_duplicates(subset=["msg_id"]).sort_values(by="published_at").reset_index(drop=True)

        # Save cache
        with open(cache_file, "w", encoding="utf-8") as f:
            json_records = df.copy()
            json_records["published_at"] = json_records["published_at"].astype(str)
            json.dump(json_records.to_dict(orient="records"), f, ensure_ascii=False, indent=2)

    return df


def extract_threat_indicators(messages_df: pd.DataFrame) -> pd.DataFrame:
    """Extracts keyword threat indicators from message texts."""
    df = messages_df.copy()
    for col_name, pattern in THREAT_PATTERNS.items():
        df[col_name] = df["text"].apply(lambda t: 1 if pattern.search(t) else 0)
    return df


def join_telegram_features_to_grid(
    grid_df: pd.DataFrame,
    messages_df: pd.DataFrame,
    window_hours: float = 1.0,
    timestamp_col: str = "timestamp",
) -> pd.DataFrame:
    """Strictly causal point-in-time join of Telegram signals to 15-min grid.

    Causal Invariant:
    For cutoff instant t_k:
    Aggregates messages where:
        t_k - window_hours <= published_at <= t_k

    Any message with published_at > t_k is STRICTLY EXCLUDED.
    """
    out = grid_df.copy()
    if messages_df.empty:
        # Fill zero indicators if no messages
        for col in list(THREAT_PATTERNS.keys()) + ["tg_msg_count"]:
            out[col] = 0.0
        return out

    msg_with_feats = extract_threat_indicators(messages_df)
    window_delta = pd.Timedelta(hours=window_hours)

    grid_ts = pd.to_datetime(out[timestamp_col], utc=True)
    msg_ts = msg_with_feats["published_at"].to_numpy()

    # Pre-extract numpy feature arrays
    indicator_cols = list(THREAT_PATTERNS.keys())
    feat_arrays = {col: msg_with_feats[col].to_numpy() for col in indicator_cols}

    n_points = len(grid_df)
    results = {col: np.zeros(n_points, dtype=float) for col in indicator_cols}
    results["tg_msg_count"] = np.zeros(n_points, dtype=float)

    for i, t_k in enumerate(grid_ts):
        # Causal filter: window [t_k - W, t_k]
        mask = (t_k - window_delta <= msg_ts) & (msg_ts <= t_k)
        count = mask.sum()
        results["tg_msg_count"][i] = float(count)
        if count > 0:
            for col in indicator_cols:
                # Max or sum of threat indicators in window
                results[col][i] = float(feat_arrays[col][mask].max())

    for k, v in results.items():
        out[k] = v

    return out
