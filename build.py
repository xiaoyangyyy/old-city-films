"""整理 Prelinger Archives 里许可清楚的城市影片，并切出短镜头。

只收录 Internet Archive 条目页面上写明许可、且允许剪辑的片子。
公有领域、CC0、CC BY、CC BY-SA、CC BY-NC、CC BY-NC-SA 留下。
带 ND（禁止演绎）的丢掉，因为切镜头本身就是演绎。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
FILMS = DATA / "films"
CLIPS = DATA / "clips"
CATALOG_PATH = DATA / "catalog.jsonl"
CLIPS_PATH = DATA / "clips.jsonl"
UA = "old-city-films/0.1 (local dataset from Internet Archive Prelinger collection)"

# 城市名按别名长度匹配。别名只用于认城市，主名写进目录。
CITIES: dict[str, list[str]] = {
    "San Francisco": ["san francisco"],
    "New York": ["new york city", "new york", "manhattan", "brooklyn", "the bronx"],
    "Los Angeles": ["los angeles", "beverly hills", "santa monica", "long beach"],
    "Washington, D.C.": ["washington, d.c.", "washington d.c.", "washington dc", "district of columbia"],
    "Chicago": ["chicago"],
    "Detroit": ["detroit"],
    "Boston": ["boston"],
    "Philadelphia": ["philadelphia"],
    "Cleveland": ["cleveland"],
    "Pittsburgh": ["pittsburgh"],
    "Seattle": ["seattle"],
    "Baltimore": ["baltimore"],
    "New Orleans": ["new orleans"],
    "St. Louis": ["st. louis", "saint louis"],
    "Minneapolis": ["minneapolis"],
    "Milwaukee": ["milwaukee"],
    "Cincinnati": ["cincinnati"],
    "Kansas City": ["kansas city"],
    "Denver": ["denver"],
    "Atlanta": ["atlanta"],
    "Dallas": ["dallas"],
    "Houston": ["houston"],
    "Miami": ["miami"],
    "Buffalo": ["buffalo, new york", "buffalo, n.y.", "buffalo ny"],
    "Newark": ["newark"],
    "Oakland": ["oakland"],
    "Berkeley": ["berkeley"],
    "Portland": ["portland"],
    "San Diego": ["san diego"],
    "San Jose": ["san jose"],
    "Sacramento": ["sacramento"],
    "Honolulu": ["honolulu"],
    "London": ["london"],
    "Paris": ["paris"],
    "Rome": ["rome"],
    "Berlin": ["berlin"],
    "Tokyo": ["tokyo"],
    "Shanghai": ["shanghai"],
    "Havana": ["havana"],
    "Montreal": ["montreal"],
    "Toronto": ["toronto"],
    "Mexico City": ["mexico city"],
}

CITY_ZH = {
    "San Francisco": "旧金山",
    "New York": "纽约",
    "Los Angeles": "洛杉矶",
    "Washington, D.C.": "华盛顿",
    "Chicago": "芝加哥",
    "Detroit": "底特律",
    "Boston": "波士顿",
    "Philadelphia": "费城",
    "Cleveland": "克利夫兰",
    "Pittsburgh": "匹兹堡",
    "Seattle": "西雅图",
    "Baltimore": "巴尔的摩",
    "New Orleans": "新奥尔良",
    "St. Louis": "圣路易斯",
    "Minneapolis": "明尼阿波利斯",
    "Milwaukee": "密尔沃基",
    "Cincinnati": "辛辛那提",
    "Kansas City": "堪萨斯城",
    "Denver": "丹佛",
    "Atlanta": "亚特兰大",
    "Dallas": "达拉斯",
    "Houston": "休斯顿",
    "Miami": "迈阿密",
    "Buffalo": "布法罗",
    "Newark": "纽瓦克",
    "Oakland": "奥克兰",
    "Berkeley": "伯克利",
    "Portland": "波特兰",
    "San Diego": "圣迭戈",
    "San Jose": "圣何塞",
    "Sacramento": "萨克拉门托",
    "Honolulu": "火奴鲁鲁",
    "London": "伦敦",
    "Paris": "巴黎",
    "Rome": "罗马",
    "Berlin": "柏林",
    "Tokyo": "东京",
    "Shanghai": "上海",
    "Havana": "哈瓦那",
    "Montreal": "蒙特利尔",
    "Toronto": "多伦多",
    "Mexico City": "墨西哥城",
}

URBAN_WORDS = [
    "downtown", "street", "streets", "traffic", "harbor", "harbour", "skyline",
    "neighborhood", "neighbourhood", "boulevard", "waterfront", "trolley",
    "streetcar", "subway", "freeway", "highway", "civic", "municipal", "slum",
    "housing", "waterfront", "city hall", "wharf", "dock", "pedestrian",
    "intersection", "avenue", "transit", "elevated", "market street",
]

SCENE_WORDS = {
    "street": ["street", "streets", "boulevard", "avenue", "intersection", "pedestrian"],
    "traffic": ["traffic", "automobile", "parking"],
    "transit": ["trolley", "streetcar", "subway", "bus ", "elevated", "transit", "railroad"],
    "harbor": ["harbor", "harbour", "wharf", "dock", "waterfront", "pier", "port"],
    "housing": ["housing", "slum", "apartment", "dwelling", "neighborhood", "neighbourhood"],
    "industry": ["factory", "industrial", "plant", "mill"],
    "bridge": ["bridge"],
    "market": ["market"],
    "park": ["park", "playground"],
    "skyline": ["skyline", "downtown"],
}

_CITY_PATTERNS: list[tuple[re.Pattern[str], str]] = []
for _city, _aliases in CITIES.items():
    for _alias in sorted(_aliases, key=len, reverse=True):
        _CITY_PATTERNS.append((re.compile(r"\b" + re.escape(_alias) + r"\b", re.I), _city))


def find_ffmpeg() -> str:
    env = os.environ.get("FFMPEG")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    bundled = Path(r"D:\qu\q\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe")
    if bundled.exists():
        return str(bundled)
    raise SystemExit("找不到 ffmpeg。把 ffmpeg 放进 PATH，或设置 FFMPEG 环境变量。")


def get_json(url: str) -> dict:
    delay = 2.0
    last = None
    for _ in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.load(response)
        except Exception as exc:  # noqa: BLE001 - 网络失败就重试
            last = exc
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"请求失败 {url}") from last


def as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(as_text(v) for v in value)
    return str(value)


def parse_runtime(value) -> float | None:
    text = as_text(value).strip()
    if not text:
        return None
    parts = text.split(":")
    if any(part.strip() == "" for part in parts):
        parts = ["0" if part.strip() == "" else part for part in parts]
    try:
        nums = [float(part) for part in parts]
    except ValueError:
        return None
    if len(nums) == 1:
        return nums[0]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def parse_year(title: str, year_field) -> int | None:
    if isinstance(year_field, int) and 1880 <= year_field <= 1975:
        return year_field
    text = as_text(year_field).strip()
    if re.fullmatch(r"\d{4}", text):
        year = int(text)
        if 1880 <= year <= 1975:
            return year
    found = re.findall(r"\b(18[8-9]\d|19[0-6]\d)\b", title)
    if found:
        return int(found[0])
    return None


def license_name(url: str) -> str | None:
    """返回许可简称。禁止演绎或不清楚的许可返回 None。"""
    low = url.lower()
    if not low:
        return None
    if "/nd/" in low or "-nd/" in low or low.rstrip("/").endswith("-nd"):
        return None
    if "publicdomain/zero" in low or "/cc0" in low or low.endswith("cc0"):
        return "cc0"
    if "publicdomain" in low:
        return "public-domain"
    if "creativecommons.org" not in low and "creativecommons" not in low:
        return None
    if "/by-nc-sa/" in low:
        return "cc-by-nc-sa"
    if "/by-nc/" in low:
        return "cc-by-nc"
    if "/by-sa/" in low:
        return "cc-by-sa"
    if "/by/" in low:
        return "cc-by"
    return None


def find_cities(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    seen: set[str] = set()
    for pattern, city in _CITY_PATTERNS:
        match = pattern.search(text)
        if match and city not in seen:
            seen.add(city)
            found.append((match.start(), city))
    found.sort()
    return [city for _, city in found]


def scene_hints(text: str) -> list[str]:
    low = text.lower()
    hints = []
    for name, words in SCENE_WORDS.items():
        if any(word in low for word in words):
            hints.append(name)
    return hints


def urban_signal(text: str, subjects: str) -> bool:
    blob = f"{text}\n{subjects}".lower()
    if any(word in blob for word in URBAN_WORDS):
        return True
    return bool(re.search(r"\bcit(y|ies)\b", subjects.lower()))


def search_licensed_films() -> list[dict]:
    query = "collection:prelinger AND mediatype:movies AND licenseurl:*"
    fields = ["identifier", "title", "year", "licenseurl", "runtime", "description", "subject"]
    fl = "".join("&fl[]=" + name for name in fields)
    docs = []
    page = 1
    num_found = None
    while True:
        url = (
            "https://archive.org/advancedsearch.php?q="
            + urllib.parse.quote(query)
            + fl
            + f"&rows=100&page={page}&output=json"
        )
        payload = get_json(url)
        response = payload["response"]
        num_found = response.get("numFound", 0)
        batch = response.get("docs", [])
        if not batch:
            break
        docs.extend(batch)
        print(f"  已取目录 {len(docs)} / {num_found}", flush=True)
        if len(docs) >= num_found:
            break
        page += 1
        time.sleep(0.4)
    return docs


def build_catalog() -> list[dict]:
    print("正在读取 Internet Archive 上许可清楚的 Prelinger 影片…")
    docs = search_licensed_films()
    kept = []
    for doc in docs:
        title = as_text(doc.get("title")).strip()
        description = as_text(doc.get("description")).strip()
        subjects = as_text(doc.get("subject")).strip()
        license_url = as_text(doc.get("licenseurl")).strip()
        kind = license_name(license_url)
        if not title or not kind:
            continue
        title_cities = find_cities(title)
        body_cities = find_cities(f"{subjects}\n{description}")
        cities = list(dict.fromkeys(title_cities + body_cities))
        text = f"{title}\n{subjects}\n{description}"
        if not cities:
            continue
        # 新闻片会顺口点到很多城市。标题里没有城市、又点了四座以上的，不收。
        if not title_cities and len(cities) > 4:
            continue
        if not title_cities and not urban_signal(text, subjects):
            continue
        year = parse_year(title, doc.get("year"))
        kept.append(
            {
                "identifier": doc.get("identifier"),
                "title": title,
                "year": year,
                "runtime_seconds": parse_runtime(doc.get("runtime")),
                "cities": cities,
                "primary_city": title_cities[0] if title_cities else cities[0],
                "city_in_title": bool(title_cities),
                "scene_hints": scene_hints(text),
                "license": kind,
                "license_url": license_url,
                "page_url": "https://archive.org/details/" + doc["identifier"],
                "description": re.sub(r"\s+", " ", description)[:400],
            }
        )
    by_id = {}
    for item in kept:
        previous = by_id.get(item["identifier"])
        if previous is None or len(item["description"]) > len(previous["description"]):
            by_id[item["identifier"]] = item
    kept = list(by_id.values())
    kept.sort(key=lambda item: (item["primary_city"], item["year"] or 9999, item["title"]))
    DATA.mkdir(parents=True, exist_ok=True)
    with CATALOG_PATH.open("w", encoding="utf-8") as handle:
        for item in kept:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    write_catalog_html(kept)
    print(f"目录写好了：{len(kept)} 部，在 {CATALOG_PATH}")
    return kept


def load_catalog() -> list[dict]:
    if not CATALOG_PATH.exists():
        return build_catalog()
    rows = []
    with CATALOG_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def metadata(identifier: str) -> dict:
    return get_json(f"https://archive.org/metadata/{urllib.parse.quote(identifier)}")


def mp4_candidates(files: list[dict]) -> list[tuple[int, str]]:
    found = []
    for info in files:
        name = info.get("name") or ""
        if not name.lower().endswith(".mp4"):
            continue
        low = name.lower()
        if "thumb" in low:
            continue
        try:
            size = int(info.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if size < 500_000 or size > 5_000_000_000:
            continue
        # 很小的 _edit 常常没有可用的画面，放在真正的衍生文件后面。
        edit_rank = 1 if "_edit" in low else 0
        found.append((edit_rank, size, name))
    found.sort()
    return [(size, name) for _, size, name in found]


def download_urls(meta: dict, identifier: str, name: str) -> list[str]:
    """直接连条目所在的服务器。archive.org 的跳转有时会指到打不开的节点。"""
    quoted = urllib.parse.quote(name)
    folder = meta.get("dir") or ""
    servers: list[str] = []
    for server in [meta.get("server"), meta.get("d1"), meta.get("d2"), *(meta.get("workable_servers") or [])]:
        if server and server not in servers:
            servers.append(server)
    urls = [f"https://{server}{folder}/{quoted}" for server in servers if folder]
    fallback = "https://archive.org/download/" + urllib.parse.quote(identifier) + "/" + quoted
    if fallback not in urls:
        urls.append(fallback)
    return urls


def download(url: str, dest: Path, expected: int | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as response, temporary.open("wb") as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        actual = temporary.stat().st_size
        if expected and actual < expected - 4096:
            temporary.unlink()
            raise RuntimeError(f"下载不完整，只有 {actual} / {expected} 字节")
        os.replace(temporary, dest)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def ffprobe_duration(ffmpeg: str, path: Path) -> float:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise RuntimeError(f"读不到片长：{path.name}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def scene_times(ffmpeg: str, path: Path) -> list[float]:
    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-i", str(path),
            "-filter:v", "select='gt(scene,0.5)',showinfo",
            "-an", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [float(value) for value in re.findall(r"pts_time:([0-9.]+)", result.stderr)]


def windows(duration: float, cuts: list[float], limit: int) -> list[tuple[float, float]]:
    bounds = [0.0]
    bounds.extend(cut for cut in cuts if 0.4 < cut < duration - 0.4)
    bounds.append(duration)
    spans: list[tuple[float, float]] = []
    for start, end in zip(bounds, bounds[1:]):
        length = end - start
        if length < 3:
            continue
        cursor = start
        remaining = length
        while remaining >= 3 and len(spans) < 80:
            piece = min(10.0, remaining)
            if piece < 3:
                break
            spans.append((cursor, piece))
            cursor += piece
            remaining -= piece
    if not spans:
        cursor = 0.0
        while cursor + 4 < duration and len(spans) < 12:
            spans.append((cursor, min(10.0, duration - cursor)))
            cursor += 10
    if len(spans) <= limit:
        return spans
    indexes = []
    for step in range(limit):
        indexes.append(round(step * (len(spans) - 1) / (limit - 1)))
    chosen = []
    for index in indexes:
        if spans[index] not in chosen:
            chosen.append(spans[index])
    return chosen


def cut_clip(ffmpeg: str, source: Path, dest: Path, start: float, duration: float) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source), "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-ac", "2", "-movflags", "+faststart",
            str(dest),
        ],
        check=True,
    )


def poster(ffmpeg: str, source: Path, dest: Path, start: float) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    attempts = [
        ["-ss", f"{max(0.0, start):.3f}", "-i", str(source), "-frames:v", "1", "-q:v", "3", str(dest)],
        ["-i", str(source), "-frames:v", "1", "-q:v", "3", str(dest)],
    ]
    last = None
    for args in attempts:
        result = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0 and dest.exists() and dest.stat().st_size > 500:
            return
        last = result.stderr.strip() or f"ffmpeg 退出码 {result.returncode}"
    raise RuntimeError(last or "静帧没有写成")


def clip_files_ready(rows: list[dict]) -> bool:
    if not rows:
        return False
    for row in rows:
        video = DATA / row["file"]
        image = DATA / row["poster"]
        if not video.exists() or video.stat().st_size < 1000:
            return False
        if not image.exists() or image.stat().st_size < 500:
            return False
    return True


def remember(identifier: str, rows: list[dict]) -> None:
    FILMS.mkdir(parents=True, exist_ok=True)
    path = FILMS / f"{identifier}.done.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def remembered(identifier: str) -> list[dict] | None:
    path = FILMS / f"{identifier}.done.json"
    if not path.exists():
        return None
    rows = json.loads(path.read_text(encoding="utf-8"))
    if clip_files_ready(rows):
        return rows
    return None


def seed_done_markers() -> None:
    """已经切好的镜头写成标记，重跑时不再解码。"""
    if not CLIPS_PATH.exists():
        return
    grouped: dict[str, list[dict]] = {}
    for line in CLIPS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        grouped.setdefault(row["identifier"], []).append(row)
    for identifier, rows in grouped.items():
        marker = FILMS / f"{identifier}.done.json"
        if marker.exists() or not clip_files_ready(rows):
            continue
        remember(identifier, rows)


def save_progress(clips: list[dict], skipped: list[dict]) -> None:
    CLIPS.mkdir(parents=True, exist_ok=True)
    with CLIPS_PATH.open("w", encoding="utf-8") as handle:
        for clip in clips:
            handle.write(json.dumps(clip, ensure_ascii=False) + "\n")
    skipped_path = DATA / "skipped.jsonl"
    with skipped_path.open("w", encoding="utf-8") as handle:
        for row in skipped:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_gallery(clips)


def clip_record(item: dict, clip_id: str, start: float, length: float) -> dict:
    return {
        "clip_id": clip_id,
        "identifier": item["identifier"],
        "title": item["title"],
        "year": item["year"],
        "primary_city": item["primary_city"],
        "cities": item["cities"],
        "scene_hints": item["scene_hints"],
        "start_seconds": round(start, 3),
        "duration_seconds": round(length, 3),
        "license": item["license"],
        "license_url": item["license_url"],
        "page_url": item["page_url"],
        "file": f"clips/{clip_id}.mp4",
        "poster": f"clips/{clip_id}.jpg",
        "note": "Scene words come from the original title and description, not from a frame-by-frame check.",
    }


def build_sample(limit_films: int, clips_per_film: int) -> list[dict]:
    free = shutil.disk_usage("D:\\").free
    if free < 2 * 1024 ** 3:
        raise SystemExit(f"D 盘剩余空间不足 2GB（现在 {free / 1024 ** 3:.1f}GB），先不下载影片。")
    catalog = load_catalog()
    ffmpeg = find_ffmpeg()
    seed_done_markers()
    clips: list[dict] = []
    skipped: list[dict] = []
    made = 0
    total = len(catalog) if not limit_films else min(limit_films, len(catalog))
    for item in catalog:
        if limit_films and made >= limit_films:
            break
        identifier = item["identifier"]
        done = remembered(identifier)
        if done:
            clips.extend(done)
            made += 1
            print(f"[{made}/{total}] 已有镜头 {identifier}", flush=True)
            continue
        print(f"[{made + 1}/{total}] {identifier}  ·  {item['title']}", flush=True)

        def give_up(reason: str) -> None:
            print(f"  跳过，{reason}", flush=True)
            skipped.append({"identifier": identifier, "title": item["title"], "reason": reason})

        try:
            info = metadata(identifier)
        except Exception as exc:  # noqa: BLE001
            give_up(f"元数据失败：{exc}")
            save_progress(clips, skipped)
            continue
        candidates = mp4_candidates(info.get("files") or [])
        if not candidates:
            give_up("没有 0.5MB 到 5GB 的 mp4")
            save_progress(clips, skipped)
            continue
        source = FILMS / f"{identifier}.mp4"
        if not source.exists():
            saved = False
            last_error = "下载失败"
            for size, name in candidates:
                if shutil.disk_usage("D:\\").free < size + 2 * 1024 ** 3:
                    last_error = "磁盘空间不够放下这一部"
                    break
                print(f"  下载 {name}（{size / 1024 ** 2:.0f}MB）", flush=True)
                try:
                    last_error = "下载失败"
                    got = False
                    for url in download_urls(info, identifier, name):
                        for _attempt in range(3):
                            try:
                                download(url, source, expected=size)
                                got = True
                                break
                            except Exception as exc:  # noqa: BLE001
                                last_error = str(exc)
                                if source.exists():
                                    source.unlink()
                                time.sleep(2)
                        if got:
                            break
                    if not got:
                        raise RuntimeError(last_error)
                    saved = True
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    print(f"  这个文件下不了：{exc}", flush=True)
                    if source.exists():
                        source.unlink()
            if not saved:
                give_up(last_error)
                save_progress(clips, skipped)
                continue
        windows_path = FILMS / f"{identifier}.windows.json"
        try:
            if windows_path.exists():
                chosen = [(row[0], row[1]) for row in json.loads(windows_path.read_text(encoding="utf-8"))]
            else:
                duration = ffprobe_duration(ffmpeg, source)
                cuts = scene_times(ffmpeg, source)
                chosen = windows(duration, cuts, clips_per_film)
                windows_path.write_text(json.dumps(chosen), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            give_up(f"切镜头失败：{exc}")
            save_progress(clips, skipped)
            continue
        if not chosen:
            give_up("没有足够长的镜头")
            save_progress(clips, skipped)
            continue
        rows = []
        try:
            for index, (start, length) in enumerate(chosen, start=1):
                clip_id = f"{identifier}_{index:02d}"
                clip_path = CLIPS / f"{clip_id}.mp4"
                image_path = CLIPS / f"{clip_id}.jpg"
                if not clip_path.exists():
                    cut_clip(ffmpeg, source, clip_path, start, length)
                if not image_path.exists():
                    poster(ffmpeg, clip_path, image_path, min(0.4, length / 3))
                rows.append(clip_record(item, clip_id, start, length))
        except Exception as exc:  # noqa: BLE001
            give_up(f"写出镜头失败：{exc}")
            save_progress(clips, skipped)
            continue
        remember(identifier, rows)
        clips.extend(rows)
        made += 1
        save_progress(clips, skipped)
        print(f"  切出 {len(rows)} 个镜头", flush=True)
        if shutil.disk_usage("D:\\").free < 5 * 1024 ** 3 and source.exists():
            source.unlink()
            print("  磁盘剩得不多，这部原片已删，镜头还在", flush=True)
        time.sleep(0.3)
    save_progress(clips, skipped)
    print(f"镜头写好了：{len(clips)} 条，来自 {made} 部片子，跳过 {len(skipped)} 部", flush=True)
    return clips


def write_catalog_html(rows: list[dict]) -> None:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["primary_city"], []).append(row)
    parts = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
        "<title>Old City Films · Catalog</title>",
        "<style>",
        "body{margin:0;background:#14120f;color:#f3ead8;font:16px/1.5 Georgia,serif}",
        "main{max-width:880px;margin:0 auto;padding:48px 24px 80px}",
        "a{color:#e7c27a} h1{font-weight:500;font-size:40px;margin:0 0 8px}",
        "p.lead{color:#cbbfa6;max-width:40em} h2{margin-top:36px;font-weight:500}",
        "ul{list-style:none;padding:0} li{padding:8px 0;border-top:1px solid #2c2822}",
        ".meta{color:#a89880;font-family:Consolas,monospace;font-size:13px}",
        "</style></head><body><main>",
        "<h1>Old City Films</h1>",
        f"<p class='lead'>{len(rows)} licensed city films from the Prelinger Archives. Each link opens the source film on the Internet Archive.</p>",
        "<p><a href='index.html'>Watch the clips</a></p>",
    ]
    for city in sorted(grouped):
        parts.append(f"<h2>{html.escape(city)}</h2><ul>")
        for row in grouped[city]:
            year = row["year"] or "year unknown"
            runtime = row["runtime_seconds"]
            clock = f"{int(runtime // 60)} min" if runtime else "runtime unknown"
            hints = ", ".join(row["scene_hints"]) or "no scene words in the description"
            parts.append(
                "<li><a href='"
                + html.escape(row["page_url"])
                + "'>"
                + html.escape(row["title"])
                + "</a><div class='meta'>"
                + html.escape(f"{year} · {clock} · {row['license']} · {hints}")
                + "</div></li>"
            )
        parts.append("</ul>")
    parts.append("</main></body></html>")
    (DATA / "catalog.html").write_text("".join(parts), encoding="utf-8")


def write_gallery(clips: list[dict]) -> None:
    cards = []
    for clip in clips:
        city = clip["primary_city"]
        year = clip["year"] or "year unknown"
        hints = ", ".join(clip["scene_hints"]) or "no scene words in the description"
        cards.append(
            "<article>"
            f"<img src='{html.escape(clip['poster'])}' alt=''>"
            f"<video src='{html.escape(clip['file'])}' controls preload='none'></video>"
            f"<h2>{html.escape(city)}</h2>"
            f"<p class='title'>{html.escape(clip['title'])}</p>"
            f"<p class='meta'>{html.escape(str(year))} · {clip['duration_seconds']:.0f} sec · {html.escape(hints)}</p>"
            f"<p class='meta'><a href='{html.escape(clip['page_url'])}'>Source film</a> · {html.escape(clip['license'])}</p>"
            "</article>"
        )
    if not cards:
        cards.append("<p>No clips yet.</p>")
    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Old City Films</title>
<style>
body {{ margin:0; background:#100e0c; color:#f4ecdf; font:16px/1.45 Georgia, serif; }}
header {{ max-width:1100px; margin:0 auto; padding:42px 24px 8px; }}
h1 {{ font-weight:500; font-size:42px; margin:0 0 8px; }}
header p {{ color:#cbbfa6; max-width:40em; }}
a {{ color:#e7c27a; }}
.grid {{ max-width:1100px; margin:0 auto; padding:12px 24px 64px; display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:22px; }}
article {{ background:#1b1814; border:1px solid #2e2923; }}
img, video {{ display:block; width:100%; background:#000; }}
article h2, article p {{ margin:8px 14px; }}
article h2 {{ font-weight:500; font-size:22px; }}
.title {{ margin-bottom:0; }}
.meta {{ color:#b3a48d; font-family:Consolas,monospace; font-size:13px; }}
</style>
</head>
<body>
<header>
<h1>Old City Films</h1>
<p>Licensed city footage from the Prelinger Archives, cut into short clips. Scene words come from the original description. City and year come from the title. <a href="catalog.html">Full catalog</a></p>
</header>
<div class="grid">
{''.join(cards)}
</div>
</body>
</html>
"""
    (DATA / "index.html").write_text(document, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="整理 Prelinger 城市影片并切出短镜头")
    parser.add_argument("command", nargs="?", choices=("all", "catalog", "sample"), default="all")
    parser.add_argument("--films", type=int, default=0, help="下载并切分的片子数量，0 表示目录里的全部")
    parser.add_argument("--clips", type=int, default=6, help="每部片子保留的镜头数")
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    if args.command in ("all", "catalog"):
        build_catalog()
    if args.command in ("all", "sample"):
        build_sample(args.films, args.clips)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
