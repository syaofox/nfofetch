# nfofetch 修复计划

## 修复顺序

按风险从低到高排列，每个修复独立可回退。优先修复 **已确认的 Bug**，然后是 **违反项目约定的代码风格问题**，再处理 **架构设计问题**，最后补充 **测试缺口**。

---

## P0 — Bug（高优先级，行为错误）

### 1. `NFOFETCH_MAX_EXTRA_IMAGES=0` 无法生效

**文件**: `app/config.py:43-44`

**问题**: `int(x) if x else 8` 中 `0` 是 falsy 值，导致 `NFOFETCH_MAX_EXTRA_IMAGES=0` 被当作未设置，返回默认值 8。

**修复**:
```
- max_extra_images = int(max_extra_images_str) if max_extra_images_str else 8
+ max_extra_images = int(max_extra_images_str) if max_extra_images_str is not None else 8
```

同时上游调用处（`file_service.py:_write_nfo_and_images`）的 `if idx > max_extra_images: break` 逻辑需要确认当 `max_extra_images=0` 时正确跳过 extrafanart（`idx` 起始为 1，`1 > 0` 成立 → 跳过，符合预期）。

---

### 2. 速率限制器并发不安全

**文件**: `app/middleware.py:13-29`

**问题**: `_locks` 字典的 `lock()` 和 `unlock()` 无锁保护。并发请求下两个线程可能同时写入 `_locks`，导致数据竞争、覆盖或 `pop` 误删。

**修复**: 给 `RequestLock` 添加 `threading.Lock()` 实例，在所有 `_locks` 读写处加锁。

```
class RequestLock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._locks: dict[str, float] = {}

    def is_locked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if key in self._locks:
                if now - self._locks[key] < LOCK_DURATION:
                    return True
                del self._locks[key]
            return False

    def lock(self, key: str) -> None:
        with self._lock:
            self._locks[key] = time.monotonic()

    def unlock(self, key: str) -> None:
        with self._lock:
            self._locks.pop(key, None)
```

---

### 3. 速率限制器内存泄漏

**文件**: `app/middleware.py:19-22`

**问题**: `is_locked()` 在访问时才清理过期条目。如果某个 key 被 `lock()` 后从未被 `is_locked()` 检查，条目永久驻留。

**修复**: 在 `lock()` 中同时触发一次惰性清理（扫描全部过期条目）。或添加后台清理协程。推荐在 `lock()` 调用前清理：

```python
def _cleanup(self) -> None:
    now = time.monotonic()
    stale = [k for k, v in self._locks.items() if now - v >= LOCK_DURATION]
    for k in stale:
        self._locks.pop(k, None)
```

在 `lock()` 末尾调用 `self._cleanup()`。

---

### 4. `get_scraper()` 静默降级

**文件**: `app/scrapers/registry.py:18-23`

**问题**: 当没有 scraper 支持给定 URL 时，返回 `SCRAPERS[0]`（当前为 JavdbScraper）。`NoSupportedScraperError` 定义了但从未使用。这会导致无意义的刮削行为（JavdbScraper 尝试处理非 javdb URL）。

**修复**: 改为抛异常，调用方自行处理 fallback：

```
def get_scraper(url: str) -> BaseScraper:
    for scraper in SCRAPERS:
        if scraper.supports(url):
            return scraper
    raise NoSupportedScraperError(f"没有找到能处理该 URL 的 scraper: {url}")
```

调用方 `scrape_movie` 处需要 catch 此异常并向用户报错。

---

### 5. `os.environ` 代理设置线程不安全

**文件**: `app/scrapers/javdb.py:62-64,112-114` 和 `app/services/file_service.py:56-62`

**问题**: `os.environ.setdefault()` 不是原子操作。尽管 `file_service.py` 用 `_proxy_env_lock` 保护了，但 javdb 中直接调用无锁。更重要的是，`os.environ` 是进程全局的，A 线程设了代理后 B 线程的请求也会走代理。

**修复**:
1. javdb.py 中移除 `os.environ.setdefault()` 调用。
2. 对于 `httpx` 路径，改用 `httpx.Client(proxies={"http://": proxy, "https://": proxy})`。
3. 对于 `curl_cffi` 路径，其 `requests.get()` 支持 `proxy=proxy` 参数。
4. `file_service.py:download_image` 同理，传入 `httpx.Client(proxies=...)`。

修改后移除 `_proxy_env_lock` 和相关注释。

---

### 6. 重复的 `_request()` 内函数

**文件**: `app/scrapers/javdb.py:69-84,118-133`

**问题**: `scrape()` 和 `search()` 各定义了一份 `_request()` 内函数，完全相同的实现（仅 URL 变量不同）。

**修复**: 提取为类的私有方法 `_request_page(url, headers, timeout) -> str`，两者共用。

---

### 7. `_extract_value_after_label` 死代码

**文件**: `app/scrapers/javdb.py:485-490`

**问题**: 方法定义了但从未被调用。

**修复**: 删除该方法。

---

## P1 — 违反项目约定

### 8. 缺失 `from __future__ import annotations`

**文件**: `app/main.py`, ~~`app/config.py`（已有）~~, ~~`app/schemas.py`（已有）~~

**问题**: `main.py` 无此 import。AGENTS.md 要求所有文件都加。

**修复**: `app/main.py` 首行添加 `from __future__ import annotations`。

---

### 9. `Optional[str]` 而非 `str | None`

**文件**: `app/config.py:6,23-24`, `app/schemas.py:3,12-13,20-21,...`, `app/scrapers/javdb.py:4,176,...`, `app/services/file_service.py:14`

**问题**: AGENTS.md 要求使用 `str | None` 而非 `Optional[str]`。

**修复**: 统一替换。同时也需要将 `List[str]` 替换为 `list[str]`，`List[Actor]` → `list[Actor]`，`Optional[HttpUrl]` → `HttpUrl | None` 等。

---

### 10. `ruff` 版本冲突

**文件**: `pyproject.toml:22` vs `pyproject.toml:29`

**问题**: `[project.optional-dependencies]` 中写 `ruff>=0.6.0`，`[dependency-groups]` 中写 `ruff>=0.15.0`。后者生效但前者造成困惑。

**修复**: 移除 `[project.optional-dependencies]` 下的 dev 块（PEP 735 的 `[dependency-groups]` 是新标准，作为唯一来源即可）。

---

## P2 — 架构 / 设计问题

### 11. 设置文件无写锁

**文件**: `app/services/settings_service.py:34-47`

**问题**: `load_user_settings()` 和 `save_user_settings()` 无文件锁。并发写入会丢失数据或读取损坏的 JSON。

**修复**: 使用 `fcntl.flock`（借鉴 `_DirectoryLock` 做法）保护设置文件的读写。或者使用一个 `threading.Lock` 在进程内做读写互斥（轻量但无法跨进程）。

建议：进程内用 `threading.Lock` 即可（该文件不大，操作快）。

---

### 12. `video_path` 无服务端路径约束

**文件**: `app/main.py:262-264`

**问题**: `/scrape` 端点接受的 `video_path` 仅检查 `vp.is_file()`，未校验是否在 `NFOFETCH_BROWSE_ROOT` 限制范围内。用户可手动构造请求写任意路径。

**修复**: 添加路径约束检查，与 `/browse` 保持一致的 `base_dir` 限制：

```python
base_dir = Path(os.getenv("NFOFETCH_BROWSE_ROOT", os.getcwd())).resolve()
try:
    vp.resolve().relative_to(base_dir)
except ValueError:
    raise PermissionError(f"视频路径超出允许范围：{vp}")
```

---

### 13. 硬编码镜像域名 `javdb565.com`

**文件**: `app/scrapers/javdb.py:42,95`

**问题**: 域名写死两处。若镜像失效需改代码。

**修复**: 提取为类常量 `MIRROR_DOMAIN = "javdb565.com"` 或从环境变量读取 `NFOFETCH_JAVDB_MIRROR`。

---

### 14. NFO XML 无格式化

**文件**: `app/services/nfo_service.py`

**问题**: `ET.tostring()` 输出单行 XML，不便于人工检查。

**修复**: 使用 `xml.dom.minidom.parseString(…).toprettyxml()` 或 `ET.indent()`（Python 3.9+）格式化输出。

---

### 15. 两阶段重命名临时文件残留

**文件**: `app/services/file_service.py:65-72,252`

**问题**: 清理 `_cleanup_orphaned_temps()` 只在下次重命名时触发。若进程在 phase1 后崩溃，临时文件残留。

**修复**: 添加 `atexit` 注册清理函数，或在应用启动时扫描所有 `NFOFETCH_BROWSE_ROOT` 下的临时文件。同时将清理改为递归搜索（不限于 `movie_dir`）。

---

### 16. `download_image` 异常静默

**文件**: `app/services/file_service.py:342-362`

**问题**: `except Exception:` 吞掉所有错误只返回 False，调用方只检查返回值但无日志。排查问题时难以定位。

**修复**: 在 except 块中添加 `logger.warning("下载失败: %s - %s", url, exc)`。

---

### 17. `exclude_unset` 合并行为问题

**文件**: `app/main.py:316`

**问题**: `settings.model_copy(update=settings.model_dump(exclude_unset=True))` 中，bool 字段如果前端传了 `false`，`exclude_unset=True` 不会把假值传进来，导致用户无法关闭某些开关。当前 `UserSettings` 无 bool 字段、目前无此问题，但需注意。

**修复**: 短期无需处理，但添加注释提醒。

---

### 18. `w == h` 时 VR 方向未处理

**文件**: `app/services/file_service.py:188-190`

**问题**: 当宽高相等时，代码既不会设置 `180_LR` 也不会设置 `360_TB`。

**修复**: 添加 `w == h` 时的默认行为（推荐 `180_LR` 或 `unknown`）。

---

## P3 — 测试缺口

### 19. 核心函数无单元测试

需要补充测试的模块：

| 函数 | 文件 |
|------|------|
| `save_assets_for_existing_video` | `app/services/file_service.py:467` |
| `_rename_single_video` | `app/services/file_service.py:209` |
| `_rename_videos_in_dir` | `app/services/file_service.py:233` |
| `_write_nfo_and_images` | `app/services/file_service.py:296` |
| `download_image` | `app/services/file_service.py:342` |
| `JavdbScraper._parse_*` (18 个方法) | `app/scrapers/javdb.py:176-468` |
| `JavdbScraper.scrape` | `app/scrapers/javdb.py:37` |
| `JavdbScraper.search` | `app/scrapers/javdb.py:91` |
| `settings_service._settings_path` | `app/services/settings_service.py:27` |
| `settings_service._default_settings_dir` | `app/services/settings_service.py:11` |

### 20. HTTP 端点无集成测试

`app/main.py` 中所有路由：`GET /`, `GET /browse`, `POST /scrape/*`, `GET/POST /api/settings`, `GET /api/scrape-task/{task_id}`, `GET /health`

### 21. CLI 入口无测试

`app/cli.py` 命令行执行路径。

---

## 执行建议

1. **分批次提交**：每个 fix 一个 commit，CI 保持绿。
2. **修复顺序**：P0 → P1 → P2 → P3，每个阶段后运行 `ruff check --fix . && ruff format . && mypy app/ && pytest` 验证。
3. **P0 和 P1 可并行修复**（互不依赖）。
4. **P2 中的 xml 格式化**可能影响现有 NFO 的 diff 行为，注意确认 Jellyfin 能正常读取格式化后的 XML。
5. **P3 测试**建议在用 pytest 编写新测试时，复用已有 `conftest.py` 中的 fixture 模式。
