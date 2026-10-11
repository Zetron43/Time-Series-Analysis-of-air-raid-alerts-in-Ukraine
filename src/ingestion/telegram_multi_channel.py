"""Multi-Channel Telegram OSINT Ingestion and Threat Fusion.

Monitors:
1. https://t.me/kpszsu       - Official Air Force of Ukraine
2. https://t.me/war_monitor  - Tactical OSINT monitoring (bombers, radar, vector tracking)
3. https://t.me/raketa_trevoga - Radar vectors and local course alarms

Strict Anti-Leakage:
- Point-in-time causal filtering (published_at <= cutoff t_k).
- Multi-channel cross-validation and consensus scoring.
"""

import json
from pathlib import Path
import re
import time
from typing import Optional, Sequence
import urllib.request
import pandas as pd
import numpy as np


MONITORED_CHANNELS = ["kpszsu", "war_monitor", "raketa_trevoga"]

THREAT_PATTERNS = {
    "tg_shahed": re.compile(r"шахед|бпла|безпілот|дрон|мопед|геран", re.IGNORECASE),
    "tg_ballistics": re.compile(r"балістик|іскандер-м|с-300|с-400|швидкісн", re.IGNORECASE),
    "tg_aviation": re.compile(r"тактичн|каб|пуск|авіаці|су-34|су-35", re.IGNORECASE),
    "tg_mig31": re.compile(r"міг-31|міг31|кинджал|саваслейк", re.IGNORECASE),
    "tg_missile": re.compile(r"ракет|калібр|х-101|х-59|х-69|ту-95|ту-22|олень|енгельс", re.IGNORECASE),
    "tg_kyiv_targeted": re.compile(r"київ|київщин|васильків|біла церква|бровар|обухів|бориспіль", re.IGNORECASE),
}


def fetch_channel_posts(
    channel_name: str,
    cache_dir: str = "data/telegram_cache",
    max_pages: int = 2,
    force_refresh: bool = False,
    cache_ttl_seconds: int = 60,
) -> pd.DataFrame:
    """Fetches messages from a public Telegram channel with a 60-second live TTL cache."""
    cache_path = Path(cache_dir) / f"{channel_name}_posts.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    cached_data = None
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            file_age = time.time() - cache_path.stat().st_mtime
            if not force_refresh and file_age < cache_ttl_seconds and cached_data:
                df = pd.DataFrame(cached_data)
                if not df.empty:
                    df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
                    df["channel"] = channel_name
                    return df.sort_values(by="published_at").reset_index(drop=True)
        except Exception:
            pass

    messages = []
    seen_ids = set()
    current_url = f"https://t.me/s/{channel_name}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for page_idx in range(max_pages):
        try:
            req = urllib.request.Request(current_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8")

            # Extract message blocks
            msg_blocks = re.findall(
                rf'<div class="tgme_widget_message[^"]*"\s+data-post="{channel_name}/(\d+)"[^>]*>(.*?)</div>\s*<!--',
                html,
                re.DOTALL,
            )

            if not msg_blocks:
                # Fallback: times and text pairs
                times = re.findall(r'<time[^>]*datetime="([^"]+)"', html)
                texts = re.findall(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
                for i, (t_str, raw_t) in enumerate(zip(times, texts)):
                    clean_t = re.sub(r"<[^>]+>", "", raw_t).strip()
                    messages.append({
                        "msg_id": f"{channel_name}_{page_idx}_{i}",
                        "published_at": t_str,
                        "text": clean_t,
                        "channel": channel_name,
                    })
                break

            for post_id, block in msg_blocks:
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                time_match = re.search(r'<time[^>]*datetime="([^"]+)"', block)
                text_match = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)

                if time_match and text_match:
                    clean_text = re.sub(r"<[^>]+>", "", text_match.group(1)).strip()
                    messages.append({
                        "msg_id": f"{channel_name}_{post_id}",
                        "published_at": time_match.group(1),
                        "text": clean_text,
                        "channel": channel_name,
                    })

            prev_match = re.search(rf'href="/s/{channel_name}\?before=(\d+)"', html)
            if prev_match:
                current_url = f"https://t.me/s/{channel_name}?before={prev_match.group(1)}"
            else:
                break
        except Exception:
            break

    df = pd.DataFrame(messages)
    if not df.empty:
        df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
        df = df.drop_duplicates(subset=["msg_id"]).sort_values(by="published_at").reset_index(drop=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            records = df.copy()
            records["published_at"] = records["published_at"].astype(str)
            json.dump(records.to_dict(orient="records"), f, ensure_ascii=False, indent=2)
        return df
    elif cached_data:
        df_old = pd.DataFrame(cached_data)
        df_old["published_at"] = pd.to_datetime(df_old["published_at"], utc=True)
        df_old["channel"] = channel_name
        return df_old.sort_values(by="published_at").reset_index(drop=True)

    return df


def fetch_all_monitoring_channels(
    channels: Sequence[str] = MONITORED_CHANNELS,
    cache_dir: str = "data/telegram_cache",
    max_pages: int = 3,
) -> pd.DataFrame:
    """Aggregates and tags messages across all target OSINT channels."""
    dfs = [fetch_channel_posts(ch, cache_dir=cache_dir, max_pages=max_pages) for ch in channels]
    valid_dfs = [d for d in dfs if not d.empty]
    if not valid_dfs:
        return pd.DataFrame(columns=["msg_id", "published_at", "text", "channel"])
    combined = pd.concat(valid_dfs, ignore_index=True)
    return combined.sort_values(by="published_at").reset_index(drop=True)


def extract_multi_channel_threats(messages_df: pd.DataFrame) -> pd.DataFrame:
    """Extracts keyword signals from messages across channels."""
    df = messages_df.copy()
    if df.empty:
        for k in THREAT_PATTERNS.keys():
            df[k] = 0
        return df

    for col_name, pattern in THREAT_PATTERNS.items():
        df[col_name] = df["text"].apply(lambda t: 1 if pattern.search(t) else 0)
    return df


def join_multi_channel_features_to_grid(
    grid_df: pd.DataFrame,
    messages_df: pd.DataFrame,
    timestamp_col: str = "timestamp",
) -> pd.DataFrame:
    """Point-in-time causal join of multi-channel OSINT intelligence.

    Calculates:
    - tg_shahed, tg_ballistics, tg_aviation, tg_mig31, tg_missile (max signal in last 1h)
    - tg_kyiv_targeted (explicit vector toward Kyiv)
    - tg_activity_15m (immediate surge in messages across all channels)
    - tg_activity_1h (sustained threat activity)
    - tg_channel_consensus (number of distinct channels sounding alarm in last 1h)
    """
    out = grid_df.copy()

    threat_cols = list(THREAT_PATTERNS.keys())
    output_feature_cols = threat_cols + [
        "tg_activity_15m",
        "tg_activity_1h",
        "tg_channel_consensus",
    ]

    if messages_df.empty:
        for col in output_feature_cols:
            out[col] = 0.0
        return out

    msg_feats = extract_multi_channel_threats(messages_df)

    grid_ts = pd.to_datetime(out[timestamp_col], utc=True)
    grid_ts_arr = grid_ts.dt.tz_convert(None).to_numpy(dtype="datetime64[ns]")

    msg_published = pd.to_datetime(msg_feats["published_at"], utc=True)
    msg_ts = msg_published.dt.tz_convert(None).to_numpy(dtype="datetime64[ns]")
    channel_arr = msg_feats["channel"].to_numpy()

    threat_arrays = {col: msg_feats[col].to_numpy() for col in threat_cols}

    n = len(out)
    results = {col: np.zeros(n, dtype=float) for col in output_feature_cols}

    delta_15m_ns = np.timedelta64(15, "m")
    delta_1h_ns = np.timedelta64(1, "h")

    idx_15m_start = np.searchsorted(msg_ts, grid_ts_arr - delta_15m_ns, side="left")
    idx_1h_start = np.searchsorted(msg_ts, grid_ts_arr - delta_1h_ns, side="left")
    idx_end = np.searchsorted(msg_ts, grid_ts_arr, side="right")

    results["tg_activity_15m"] = (idx_end - idx_15m_start).astype(float)
    results["tg_activity_1h"] = (idx_end - idx_1h_start).astype(float)

    for i in range(n):
        s_1h = idx_1h_start[i]
        e = idx_end[i]
        if e > s_1h:
            unique_channels = len(np.unique(channel_arr[s_1h:e]))
            results["tg_channel_consensus"][i] = float(unique_channels)
            for col in threat_cols:
                results[col][i] = float(threat_arrays[col][s_1h:e].max())

    for col, arr in results.items():
        out[col] = arr

    return out
