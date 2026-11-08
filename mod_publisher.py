# -*- coding: utf-8 -*-
"""网易模组发布器 v11 —— 单窗口：窗口即 Edge 本体，界面 ui.html，Python 引擎
经 Playwright 绑定提供 RPC；引擎线程空闲时泵消息保证绑定实时可达。"""
import base64
import ctypes
import json
import os
import re
import sys
import subprocess
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

import publish_api as PA
import publish_core as core

APP_VERSION = "26.11.11"
REPO_URL = "https://github.com/InvisibleGuardian007/ModPublisher"

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

if getattr(sys, "frozen", False):
    UI_FILE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "ui.html"
else:
    UI_FILE = Path(__file__).resolve().parent / "ui.html"


# ================= 已运行实例的窗口定位/调出 =================
def _win_class(h):
    buf = ctypes.create_unicode_buffer(64)
    ctypes.windll.user32.GetClassNameW(h, buf, 64)
    return buf.value


def _publisher_edge_pids():
    marker = "%s*profile*" % core.APP_DIR.name
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"name='msedge.exe'\" | Where-Object "
             "{ $_.CommandLine -like '*%s*' -and $_.CommandLine -notlike '*--type=*' } "
             "| Select-Object -ExpandProperty ProcessId" % marker],
            capture_output=True, text=True, timeout=15,
            creationflags=core.CREATE_NO_WINDOW)
        return [int(x) for x in (out.stdout or "").split()]
    except Exception:
        return []


def focus_publisher_window(prefixes=None):
    """把发布器界面调到前台：优先经 CDP 激活应用页（--app 本地地址或
    file:// 兜底），失败再找发布器专用窗口。"""
    try:
        import urllib.request as _u
        with _u.urlopen("http://127.0.0.1:9222/json/version", timeout=2):
            pass
        from playwright.sync_api import sync_playwright
        prefixes = prefixes or [UI_FILE.as_uri()]
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=4000)
            for c in b.contexts:
                for pg in c.pages:
                    if (pg.url or "").startswith(tuple(prefixes)):
                        try:
                            pg.bring_to_front()
                        except Exception:
                            pass
                        return True
            return False
    except Exception:
        pass
    user32 = ctypes.windll.user32
    pids = set(_publisher_edge_pids())
    hit = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _l):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(h) \
                and _win_class(h) == "Chrome_WidgetWin_1":
            hit.append(h)
            return False
        return True

    user32.EnumWindows(cb, 0)
    if not hit:
        return False
    user32.ShowWindow(hit[0], 9)          # SW_RESTORE
    user32.SwitchToThisWindow(hit[0], True)
    user32.SetForegroundWindow(hit[0])
    return True


class Host(object):
    """引擎+API+RPC。专用引擎线程拥有全部 Playwright 对象（同步API线程约束）；
    绑定/外部调用经 submit() 投递到该线程串行执行，避免嵌套死锁。"""

    def __init__(self, cfg, log=lambda m: None):
        self.cfg = cfg
        self.log = log
        self.api = PA.Api(log=self.js_log)
        self.eng = None
        self.page = None
        self.api_page = None    # 停靠页（ensure 时创建/复用）
        self.rows = []          # [(name, rid)]
        self.detail_cache = {}
        self._tid = None
        import queue as _q
        self._q = _q.Queue()
        self._ready = threading.Event()
        self._ui_event = None
        self._closed = threading.Event()
        self.exit_on_close = True   # --reside 常驻模式置 False：关窗不退出，自动重开
        self._start_err = None
        self._sse = []              # 手机端 SSE 订阅队列（日志/进度推送）
        self.web_token = None
        self.http_port = 8765
        self.lan_ip = "127.0.0.1"

    # ---------- 引擎线程 ----------
    def start(self, timeout=90):
        threading.Thread(target=self._loop, daemon=True).start()
        if not self._ready.wait(timeout):
            raise RuntimeError("引擎启动超时")
        if self._start_err:
            raise RuntimeError("引擎启动失败: %s" % self._start_err)

    def _loop(self):
        self._tid = threading.get_ident()
        try:
            self.ensure()
        except Exception as e:
            self._start_err = str(e)
            self._ready.set()
            return
        self._ready.set()
        while not self._closed.is_set():
            try:
                fn, ev, box = self._q.get_nowait()
            except Exception:
                # 空闲时用 playwright 等待泵连接消息：绑定通知只有在本线程
                # 处于 playwright 调用中才会派发，否则页面点击永远无响应
                try:
                    self.page.wait_for_timeout(120)
                except Exception:
                    self._closed.wait(0.12)
                continue
            try:
                val = fn()
                if box is not None:
                    box.append(("ok", val))
            except Exception as e:
                if box is not None:
                    box.append(("err", e))
            if ev is not None:
                ev.set()

    def ui_event(self, kind, payload):
        """引擎线程 → UI 页面推送（进度等）；同时推给手机端 SSE 订阅者。"""
        self._sse_push({"kind": kind, "payload": payload})
        if self._ui_event:
            try:
                self._ui_event(kind, json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass

    def _sse_push(self, obj):
        for q in list(self._sse):
            try:
                q.put_nowait(obj)
            except Exception:
                pass

    def web_url(self):
        return "http://%s:%d/ui?token=%s" % (
            self.lan_ip, self.http_port, self.web_token)

    def on_engine_thread(self):
        return self._tid == threading.get_ident()

    def submit(self, fn, timeout=600):
        if self.on_engine_thread():
            return fn()
        ev = threading.Event()
        box = []
        self._q.put((fn, ev, box))
        if not ev.wait(timeout):
            raise RuntimeError("RPC执行超时")
        tag, val = box[0]
        if tag == "err":
            raise val
        return val

    # ---------- 引擎 ----------
    def ensure(self):
        """确保引擎与浏览器可用；窗口被关/崩溃后自动重开（配合 --reside 常驻）。"""
        if self.eng and self.eng._ctx is not None:
            try:
                if not self.eng._ctx.is_closed():
                    return self.eng
            except Exception:
                pass
            print("[引擎] 浏览器窗口已丢失，自动重开…", flush=True)
            self.eng._ctx = None
            self.eng.page = None
            self.eng._editor_mod = None
        if self.eng is None:
            self.eng = core.BrowserEngine(self.cfg, lambda k, p: None)
        self.eng._ensure_browser()
        ctx = self.eng._ctx
        # 绑定与注入都放到 context 级：随页面导航持续生效
        ctx.expose_binding("__pyRequest", self._on_request)
        main, dock = self._dedupe_pages(ctx)
        self.page = main
        # 主页面先就位：窗口立刻显示发布器界面（不被停靠页加载等待挡在 about:blank）
        _ui_target = self.cfg.get("app_url") or UI_FILE.as_uri()
        if not (self.page.url or "").startswith(_ui_target.split("?")[0]):
            self.page.goto(_ui_target, wait_until="domcontentloaded")
        self._ui_event = lambda kind, pj: self.page.evaluate(
            "([k,j])=>window.__mpEvent&&window.__mpEvent(k,j)", [kind, pj])
        try:
            self.page.bring_to_front()
        except Exception:
            pass
        # 停靠页：常驻平台域，API 全部经它 fetch（浏览器原生管理轮换cookie）
        if dock is None:
            dock = ctx.new_page()
            try:
                dock.goto("https://mcdev.webapp.163.com/",
                          wait_until="domcontentloaded", timeout=30000)
                dock.wait_for_timeout(3500)
            except Exception:
                pass
        self.api_page = None   # 传输走 ctx.request，不再需要可见停靠页
        self.api.set_context(ctx)
        try:
            self.page.bring_to_front()
        except Exception:
            pass
        try:
            ctx.on("close", lambda _c: self._on_ctx_closed())
            # 附加模式：窗口被用户关掉 = 连接断开，普通模式下进程随之退出
            if self.eng._attached and self.eng._browser is not None:
                self.eng._browser.on("disconnected", lambda *_: self._on_ctx_closed())
        except Exception:
            pass
        return self.eng

    def _dedupe_pages(self, ctx):
        """附加模式下浏览器里有用户的个人标签页，绝不劫持：
        发布器 UI 页存在则复用（多余的去重），不存在就**新开一个追加在最后**；
        平台停靠页同理，只复用确实是平台首页/登录页/列表页的（那是我们开的）。
        返回 (主页面, 可复用的停靠页或 None)。"""
        def _alive(pg):
            try:
                return not pg.is_closed()
            except Exception:
                return False

        ui_pages = [pg for pg in ctx.pages
                    if (pg.url or "").startswith(UI_FILE.as_uri())
                    or (pg.url or "").startswith(
                        (self.cfg.get("app_url") or "\u0000").split("?")[0])]
        for pg in ui_pages[1:]:
            try:
                pg.close()
            except Exception:
                pass
        # about:blank 视为可丢弃（新拉起 Edge 的初始页/迁移残株）：优先复用，多余关闭
        blanks = [pg for pg in ctx.pages
                  if pg not in ui_pages and (pg.url or "") == "about:blank"
                  and _alive(pg)]
        if ui_pages:
            main = ui_pages[0]
            # 复用 HTTP 应用页时重载：把页面重新绑定到本会话的 RPC 通道
            if (main.url or "").startswith("http://127.0.0.1:8765/ui"):
                try:
                    main.reload(wait_until="domcontentloaded")
                except Exception:
                    pass
        elif blanks:
            main = blanks[0]
        else:
            main = ctx.new_page()
        for pg in blanks:
            if pg is not main:
                try:
                    pg.close()
                except Exception:
                    pass
        _home = ("https://mcdev.webapp.163.com/")
        dock = None
        for pg in ctx.pages:
            if pg is main or not _alive(pg):
                continue
            u = (pg.url or "")
            if u == _home or u.startswith(_home + "#"):
                dock = pg
                break
        return main, dock

    def _on_ctx_closed(self):
        """普通模式：窗口关 = 进程退出（否则僵尸进程占 8765，下次启动弹『已在运行中』）；
        --reside 常驻模式：不退出，下次接口调用自动重开。"""
        if self._closed.is_set():
            return
        if self.exit_on_close:
            self._closed.set()
            print("[引擎] 浏览器窗口已关闭，进程退出", flush=True)
        else:
            print("[引擎] 浏览器窗口已关闭；下次接口调用自动重开", flush=True)

    def _back_to_ui(self):
        try:
            self.page.goto(self.cfg.get("app_url") or UI_FILE.as_uri(),
                           wait_until="domcontentloaded")
        except Exception:
            pass

    def js_log(self, msg):
        self._sse_push({"kind": "log", "payload": msg})
        def push():
            try:
                # 界面日志抽屉（__mpLog）；无抽屉的旧页面回退 #log 节点
                self.page.evaluate(
                    "m=>{if(window.__mpLog)window.__mpLog(m);"
                    "else{const l=document.getElementById('log');"
                    "if(l)l.textContent+=m+'\\n'}}", msg)
            except Exception:
                pass
        try:
            self.submit(push, timeout=10)
        except Exception:
            pass

    # ---------- RPC ----------
    def _on_request(self, _b, action, payload_json, call_id):
        """绑定回调只入队立即返回（此时处于 Playwright 派发栈，禁止嵌套调用），
        引擎线程空闲时执行并经 evaluate 回推结果。"""
        self._q.put((lambda: self._exec_and_resolve(action, payload_json, call_id),
                     None, None))
        return "1"

    def _exec_and_resolve(self, action, payload_json, call_id):
        try:
            payload = json.loads(payload_json or "{}")
            data = getattr(self, "rpc_" + action)(payload)
            out = {"ok": True, "data": data}
        except Exception as e:
            out = {"ok": False, "error": str(e)}
        try:
            self.page.evaluate(
                "([i,j])=>window.__pyResolve && window.__pyResolve(i,j)",
                [call_id, json.dumps(out, ensure_ascii=False)])
        except Exception:
            pass

    # ---------- 动作 ----------
    def _local_map(self):
        m = {}
        for mod in self.cfg["mods"]:
            info = core.mod_info(mod)
            for row_name, _rid in self.rows:
                kw = mod.get("resource_keyword") or ""
                if kw and kw in row_name:
                    m[row_name] = {"id": mod["id"],
                                   "version": info.get("version"),
                                   "count": info.get("count"),
                                   "zip_latest": info.get("zip_latest"),
                                   "name_suggest": info.get("name_suggest"),
                                   "note_suggest": info.get("note_suggest")}
        return m

    def rpc_boot(self, _p):
        self.ensure()
        profile = None
        rows = []
        err = None
        for attempt in range(2):
            try:
                u = self.api.user_info()
                profile = {"nickname": u["nickname"], "avatar": u["avatar"]}
                rows = self.api.list_items()
                err = None
                break
            except Exception as e:
                err = str(e)
                try:
                    self.api_page.reload(wait_until="domcontentloaded")
                    self.api_page.wait_for_timeout(3000)
                except Exception:
                    pass
        if err:
            self._boot_err = err
            self.js_log("[API] 未登录或读取失败: %s" % err)
        self.rows = [(r["name"], r["rid"]) for r in rows]
        return {"profile": profile, "rows": rows, "local": self._local_map()}

    def rpc_read_item(self, p):
        name = p.get("name")
        rid = self._rid(name)
        if rid:
            try:
                d = self.api.detail(rid)
            except Exception as e:
                # 自愈：停靠页被关则自动重建最小化，再试一次；仍失败才走副页兜底
                try:
                    self.ensure()
                    d = self.api.detail(rid)
                except Exception as e2:
                    self.js_log("[API] 详情读取失败转浏览器: %s / 重试: %s"
                                % (e, e2))
                    d = None
            if d is not None:
                self.detail_cache[name] = d
                res_list = d.get("res") if isinstance(d.get("res"), list) else []
                res0 = res_list[0] if res_list else {}
                tags = []
                for t in (d.get("tag") or []):
                    tags.append((t.get("tag_name") or t.get("name") or "")
                                if isinstance(t, dict) else str(t))
                det_html, det_key = None, None
                for k in ("pe_game_introduction", "info"):
                    v = d.get(k) or ""
                    if "<p>" in v or "<img" in v:
                        det_html, det_key = v, k
                        break
                price = ""
                if d.get("price_rank"):
                    price = "第%s档 %s钻" % (d.get("price_rank"), d.get("price"))
                si = d.get("sync_item_info")
                fields = {}
                for k, v in d.items():
                    if k in ("res", "channel", "video_info_list", "achievement_configs"):
                        fields[k] = json.dumps(v, ensure_ascii=False)
                    elif isinstance(v, (str, int, float, bool)) or v is None:
                        fields[k] = v
                    else:
                        fields[k] = json.dumps(v, ensure_ascii=False)
                si_raw = d.get("sync_item_info") or {}
                si = json.loads(si_raw) if isinstance(si_raw, str) else si_raw
                pc_chans = []
                for c in ((si.get("channel") or []) if isinstance(si, dict) else []):
                    if not isinstance(c, dict):
                        continue
                    cu = c.get("channel_url")
                    if isinstance(cu, dict):
                        cu = json.loads(cu.get("body") or "{}").get("url", "")
                    pc_chans.append({"id": c.get("channel_id"),
                                     "url": cu if isinstance(cu, str) else "",
                                     "version": c.get("version")})
                chans = []
                for c in (d.get("channel") or []):
                    if not isinstance(c, dict):
                        continue
                    cu = c.get("channel_url")
                    if isinstance(cu, dict):  # 未保存的上传回执形态
                        cu = json.loads(cu.get("body") or "{}").get("url", "")
                    chans.append({"id": c.get("channel_id"),
                                  "url": cu if isinstance(cu, str) else "",
                                  "version": c.get("version")})
                vil = d.get("video_info_list") or []
                video = vil[0] if vil and isinstance(vil[0], dict) else None
                guides = [{"title": g.get("title"), "status": g.get("status")}
                          for g in (d.get("guide_list") or [])
                          if isinstance(g, dict)]
                return {
                    "fields": fields,
                    "banner_pic": d.get("banner_pic") or None,
                    "channels": chans,
                    "pc_channels": pc_chans,
                    "video": video,
                    "guides": guides,
                    "name": d.get("item_name"),
                    "mod_code": str(d.get("vanity_number") or ""),
                    "res_version": str(d.get("item_version") or ""),
                    "price": price,
                    "zip": res0.get("res_name"),
                    "tags": [t for t in tags if t],
                    "activity": d.get("activity_desc") or "",
                    "pc_intro": (si.get("brief") if isinstance(si, dict) else "") or "",
                    "note": d.get("update_summary") or "",
                    "detail_html": det_html,
                    "detail_key": det_key,
                }
        # 浏览器兜底（在专用副页进行，绝不占用主应用窗口）
        cur = self.eng.read_current(name)
        cur.pop("detail_plain", None)
        return cur

    def rpc_login(self, _p):
        """登录在**独立窗口**完成（常规桌面软件的授权体验）：
        主窗口始终停留在应用界面；登录成功后该窗口自动关闭并回到应用。"""
        self.ensure()
        lp = self.eng._ctx.new_page()
        try:
            lp.goto(self.cfg["list_url"], wait_until="domcontentloaded",
                    timeout=30000)
        except Exception:
            pass
        self.js_log("[登录] 已打开登录窗口，完成后会自动关闭并返回应用")
        ok = False
        deadline = time.time() + 600
        while time.time() < deadline:
            try:
                lp.wait_for_timeout(2000)
            except Exception:
                break
            try:   # 以接口会话为准判定登录成功（页面跳转形态不可靠）
                self.api.user_info()
                ok = True
                break
            except Exception:
                pass
        try:
            lp.close()
        except Exception:
            pass
        try:
            self.api.user_info()
        except Exception:
            ok = False
        return {"ok": bool(ok)}

    def _upload_b64(self, b64, mime, prefix="mp_img"):
        """base64 → 临时文件 → 平台直传，返回 FileInfoDTO；临时文件必清理。"""
        suffix = ".jpg" if ("jpeg" in (mime or "") or "jpg" in (mime or "")) else ".png"
        f = Path(tempfile.gettempdir()) / ("%s_%d%s" % (prefix, time.time_ns(), suffix))
        f.write_bytes(base64.b64decode(b64))
        try:
            return self.api.upload("image", f, mime or "image/png")
        finally:
            try:
                f.unlink()
            except Exception:
                pass

    def rpc_upload_image(self, p):
        info = self._upload_b64(p["b64"], p.get("mime"))
        return json.loads(info["body"]).get("url")

    def rpc_publish(self, p):
        name = p.get("name")
        mod = self._mod(name)
        rid = self._rid(name)
        detail = self.detail_cache.get(name)
        if rid and detail is None:
            # 缓存缺失（界面未先“读取”）时现拉详情，避免误入浏览器兜底慢通道
            try:
                detail = self.api.detail(rid)
                self.detail_cache[name] = detail
            except Exception as e:
                self.js_log("[API] 详情拉取失败: %s" % e)
        if rid and detail is not None:
            try:
                return self._api_publish(rid, mod, detail, p, name=name)
            except PA.DetailValidationError as e:
                # 校验/回读失败转浏览器也一样被拒或截断，直接抛给调用方
                self.js_log("[API] %s" % e)
                raise
            except Exception as e:
                self.js_log("[API] 发布失败转浏览器: %s" % e)
        # 浏览器兜底
        zip_path = None
        if p.get("zip"):
            zip_path = core.pack(mod)
            self.js_log("[引擎] 打包完成: %s" % os.path.basename(zip_path))
        self.eng.apply_and_save(name, {
            "zip_path": zip_path, "boost": p.get("boost"),
            "name": p.get("item_name"), "activity": p.get("activity_desc"),
            "pc_intro": p.get("pc_intro"), "note": p.get("update_summary"),
            "detail_html": p.get("detail_html")})
        return {"fallback": True}

    def _api_publish(self, rid, mod, detail, p, name=None):
        changes = dict(p.get("changes") or {})  # 全字段：界面脏值直接生效
        if p.get("item_name"):
            changes["item_name"] = p["item_name"]
        note = p.get("update_summary") or changes.get("update_summary")
        if note:
            note = str(note)[:200]
            changes["update_summary"] = note
            # 平台展示用的 current_change_log 跟随纪要（显式改过则尊重显式值）
            changes.setdefault("current_change_log", note)
        if p.get("activity_desc"):
            changes["activity_desc"] = p["activity_desc"]
        pc_intro = p.get("pc_intro") or changes.pop("pc_intro", None)
        if pc_intro:
            si = detail.get("sync_item_info")
            si = si if isinstance(si, dict) else {}
            si["brief"] = pc_intro
            detail["sync_item_info"] = si
        if p.get("detail_html"):
            key = p.get("detail_key") or (
                "pe_game_introduction"
                if "<p>" in (detail.get("pe_game_introduction") or "") else "info")
            changes[key] = p["detail_html"]
        # ---- 发布护栏：详情标签矫正 + 字数/图数校验（先失败，不浪费上传） ----
        det_key = p.get("detail_key") if p.get("detail_html") else None
        for k in ("pe_game_introduction", "info"):
            v = changes.get(k)
            if isinstance(v, str) and "<" in v:
                v = PA.sanitize_detail_html(v)
                n_img, ln = PA.validate_detail_html(v)
                changes[k] = v
                det_key = det_key or k
                self.js_log("[API] 详情校验 %s：%d字/%d图（上限 %d/%d）"
                            % (k, ln, n_img, PA.DETAIL_BUDGET, PA.DETAIL_IMGS))
        zip_name = None
        if p.get("zip"):
            def prog(frac, msg):
                self.ui_event("pack_progress", {"frac": frac, "msg": msg})
            z = PA.pack_project(core.project_dir(mod), progress=prog)
            self.ui_event("pack_progress", {"frac": 1.0, "msg": "打包完成"})
            self.js_log("[API] 打包完成: %s" % os.path.basename(z))
            self.ui_event("pack_progress", {"frac": None, "msg": "直传中…"})
            info = self.api.upload("zip_package", z, "application/zip")
            self.ui_event("pack_progress", {"frac": None, "msg": ""})
            self.js_log("[API] 直传完成 sign=%s…" % info["sign"][:10])
            changes["new_res"] = info
            changes["new_res_name"] = os.path.basename(z)
            changes["add_version"] = bool(p.get("boost"))
            zip_name = os.path.basename(z)
        body = PA.build_update_body(detail, changes)
        self.api.update_item(rid, body)
        self.js_log("[API] 保存成功（update）")
        r, fresh = self._verify_publish(rid, detail, changes, det_key, zip_name)
        if name:
            self.detail_cache[name] = fresh  # 回读的新详情作为缓存基线
        r.setdefault("zip", zip_name or ((fresh.get("res") or [{}])[0]
                                         .get("res_name") if fresh.get("res") else None))
        return r

    def _verify_publish(self, rid, old_detail, changes, key, zip_name):
        """update 后立即回读验证：平台对超预算详情**静默截断吞图**、包替换失败均无报错，
        只有回读能发现。异常等 2 秒复查一次（排除读延迟）再判死。
        返回 (回执, 回读到的最新详情)——回执含新旧版本号、详情字数/图数、落库包名。"""
        sent_html = (changes.get(key) or "") if key else ""
        sent_imgs = sent_html.count("<img")
        sent_len = PA.editor_len(sent_html) if sent_html else 0
        d = self.api.detail(rid)
        truncated = zip_bad = False
        got_zip = ""
        for attempt in (1, 2):
            html2 = (d.get(key) or "") if key else ""
            res0 = (d.get("res") or [{}])[0] if isinstance(d.get("res"), list) else {}
            got_zip = os.path.basename(res0.get("res_name") or "")
            truncated = bool(sent_html) and (
                html2.count("<img") < sent_imgs
                or PA.editor_len(html2) < sent_len - 2)
            zip_bad = bool(zip_name) and got_zip != zip_name
            if not truncated and not zip_bad:
                new_ver = str(d.get("item_version") or "")
                old_ver = str(old_detail.get("item_version") or "")
                if changes.get("add_version") and new_ver == old_ver:
                    self.js_log("[警告] 回读版本仍为 %s，平台可能未提升版本" % new_ver)
                return {"res_version": new_ver or old_ver,
                        "old_version": old_ver,
                        "detail_len": PA.editor_len(html2) if sent_html else None,
                        "detail_imgs": html2.count("<img") if sent_html else None,
                        "zip": got_zip or None}, d
            if attempt == 1:
                self.js_log("[API] 回读异常（截断=%s 包=%s），2 秒后复查…"
                            % (truncated, got_zip or "无"))
                time.sleep(2)
                d = self.api.detail(rid)
        if truncated:
            html2 = (d.get(key) or "") if key else ""
            raise PA.DetailValidationError(
                "回读验证失败：详情被平台静默截断（图 %d→%d、字 %d→%d），"
                "大概率超字数上限" % (sent_imgs, html2.count("<img"),
                                    sent_len, PA.editor_len(html2)))
        raise PA.DetailValidationError(
            "回读验证失败：平台包仍为 %r，期望 %r" % (got_zip, zip_name))

    def rpc_submit(self, p):
        name = p.get("name")
        rid = self._rid(name)
        if rid:
            try:
                self.api.apply_review(rid, "")
                self.js_log("[API] 已提交审核")
                return {"ok": True}
            except Exception as e:
                self.js_log("[API] 提审失败转浏览器: %s" % e)
        self.eng.open_editor(re.escape(name), key=name)
        self.eng.submit()
        return {"ok": True, "fallback": True}


    # ---------- 图片/视频槽位 RPC ----------
    def rpc_slot_save(self, p):
        """图片槽位：key=banner(组件ICON) 或 channel:<id>。上传并保存。"""
        rid = self._rid(p["name"])
        info = self._upload_b64(p["b64"], p.get("mime"), "mp_slot")
        url = json.loads(info["body"]).get("url")
        detail = self.api.detail(rid)
        key = p["key"]
        if key == "banner":
            detail["banner_pic"] = url
            changes = {"banner_pic": url}
        else:
            cid = int(key.split(":", 1)[1])
            chan = detail.get("channel") or []
            hit = False
            for c in chan:
                if int(c.get("channel_id", -1)) == cid:
                    # 替换槽位：channel_url=上传回执（平台 update 接口要求的 DTO 形态）
                    c["channel_url"] = info
                    hit = True
                    break
            if not hit:
                chan.append({"channel_id": cid, "channel_url": info, "version": 1})
            detail["channel"] = chan
            changes = {}
        body = PA.build_update_body(detail, changes)
        self.api.update_item(rid, body)
        return {"url": url}

    def rpc_pc_slot_save(self, p):
        """PC图片槽位：sync_item_info.channel（channel_id 1001/1002/…）"""
        rid = self._rid(p["name"])
        info = self._upload_b64(p["b64"], p.get("mime"), "mp_pcs")
        url = json.loads(info["body"]).get("url")

        def job():
            detail = self.api.detail(rid)
            si = detail.get("sync_item_info") or {}
            if isinstance(si, str):
                si = json.loads(si or "{}")
            chan = si.get("channel") or []
            cid = int(p["key"].split(":", 1)[1])
            hit = False
            for c in chan:
                if int(c.get("channel_id", -1)) == cid:
                    c["channel_url"] = info
                    hit = True
                    break
            if not hit:
                chan.append({"channel_id": cid, "channel_url": info,
                             "version": 1})
            si["channel"] = chan
            detail["sync_item_info"] = si
            body = PA.build_update_body(detail, {})
            self.api.update_item(rid, body)
            return {"url": url}
        return self.submit(job)

    def rpc_video_save(self, p):
        """视频+封面：上传并保存 video_info_list=[{cover,url,size}]"""
        rid = self._rid(p["name"])
        up = p.get("video") or {}
        cv = p.get("cover") or {}
        if not up.get("b64"):
            raise RuntimeError("缺少视频文件")
        vf = Path(tempfile.gettempdir()) / ("mp_v%d.mp4" % time.time_ns())
        vf.write_bytes(base64.b64decode(up["b64"]))
        try:
            vinfo = self.api.upload("video", vf, "video/mp4")
        finally:
            try:
                vf.unlink()
            except Exception:
                pass
        vurl = json.loads(vinfo["body"]).get("url")
        curl = None
        if cv.get("b64"):
            cinfo = self._upload_b64(cv["b64"], cv.get("mime") or "image/jpeg",
                                     "mp_cov")
            curl = json.loads(cinfo["body"]).get("url")
        old = (self.api.detail(rid).get("video_info_list") or [{}])
        old0 = old[0] if old else {}
        entry = {"cover": curl or old0.get("cover", ""),
                 "url": vurl, "size": int(up.get("size") or 0)}
        detail = self.api.detail(rid)
        detail["video_info_list"] = [entry]
        body = PA.build_update_body(detail, {"video_info_list": [entry]})
        self.api.update_item(rid, body)
        return entry

    # ---------- AI 助手（OpenAI 兼容 /chat/completions，Key 只存本机配置） ----------
    def rpc_ai_get(self, _p):
        return {"ai": self.cfg.get("ai") or {},
                "ai_image": self.cfg.get("ai_image") or {}}

    def rpc_ai_save(self, p):
        ai = {"base_url": str(p.get("base_url") or "").strip().rstrip("/"),
              "api_key": str(p.get("api_key") or "").strip(),
              "model": str(p.get("model") or "").strip()}
        for k, v in ai.items():
            if not v:
                raise RuntimeError("存在未填项：%s" % k)
        self.cfg["ai"] = ai
        im = p.get("ai_image") or {}
        # 生图配置可整体留空 = 跟随上方 AI 配置
        self.cfg["ai_image"] = {
            "base_url": str(im.get("base_url") or "").strip().rstrip("/"),
            "api_key": str(im.get("api_key") or "").strip(),
            "model": str(im.get("model") or "").strip()}
        core.save_config(self.cfg)
        self.js_log("[AI] 配置已保存（%s / %s）" % (ai["base_url"], ai["model"]))
        return {"ok": True}

    @staticmethod
    def _ai_prompt(kind, text, name, key=""):
        if kind == "test":
            return "你是连通性测试器。", "回复 ok 两个字母即可。"
        if kind == "note":
            return ("你是网易《我的世界》模组商店的运营文案写手。输出PE更新纪要："
                    "≤200字、纯文本、直接输出正文，不要任何解释/标题/Markdown。"
                    "格式惯例：以「本次更新：」或版本号开头，要点用「；」连接，"
                    "突出新内容与体验改进。"), \
                   ("模组：%s\n原始纪要/更新日志：\n%s" % (name or "未知名", text))
        if kind == "pc":
            return ("你是网易《我的世界》模组商店的运营文案写手。输出PC端模组简介："
                    "≤100字、一到两句话、纯文本直接输出正文，突出核心卖点与玩家收益。"), \
                   ("模组：%s\n原始简介：\n%s" % (name or "未知名", text))
        if kind == "activity":
            return ("你是网易《我的世界》模组商店运营。改写「活动参与说明」："
                    "≤60字、一到两句话、纯文本直接输出正文，说明参与的活动"
                    "与玩家能获得的收益。"), \
                   ("模组：%s\n当前说明：\n%s" % (name or "未知名", text))
        if kind == "field":
            return ("你是网易模组商店的字段编辑助手。按字段含义把当前值改写为"
                    "更合适的值：纯文本、直接输出新值、不要任何解释；"
                    "若当前值是JSON结构，保持原结构只优化其中的文本内容。"), \
                   ("作品：%s\n字段名：%s\n当前值：\n%s"
                    % (name or "未知名", key or "(未知)", text))
        return ("你是网易《我的世界》模组商店的详情文案写手。输出PE商店详情页正文："
                "总字数≤360字（平台按段落计费，超了会静默截断），3~8个自然段，"
                "每段一行、用换行分隔；纯文本输出，禁止Markdown符号。"
                "第一段总览特色，中段每行一个玩法亮点，末段引导下载。"), \
               ("模组：%s\n当前详情文字：\n%s" % (name or "未知名", text))

    def rpc_ai_polish(self, p):
        ai = dict(self.cfg.get("ai") or {})
        for k in ("base_url", "api_key", "model"):
            if p.get(k):
                ai[k] = str(p[k]).strip()
        base = (ai.get("base_url") or "").rstrip("/")
        key, model = ai.get("api_key"), ai.get("model")
        if not (base and key and model):
            raise RuntimeError("未配置 AI：点顶栏「⚙ 设置」填写接口地址/Key/模型")
        kind = p.get("kind") or "note"
        text = str(p.get("text") or "").strip()
        if kind != "test" and not text:
            raise RuntimeError("没有可润色的内容")
        sys_p, usr = self._ai_prompt(kind, text, p.get("name") or "",
                                     p.get("key") or "")
        import requests as _rq
        r = _rq.post(base + "/chat/completions",
                     headers={"Authorization": "Bearer %s" % key},
                     json={"model": model, "temperature": 0.7,
                           "messages": [{"role": "system", "content": sys_p},
                                        {"role": "user", "content": usr}]},
                     timeout=(10, 120))
        if r.status_code != 200:
            raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:200]))
        out = ((r.json().get("choices") or [{}])[0].get("message") or {}).get(
            "content") or ""
        out = out.strip()
        if not out:
            raise RuntimeError("AI 返回为空")
        return {"text": out, "reply": out[:60]}

    def rpc_ai_image(self, p):
        """文生图（OpenAI 兼容 /images/generations）；生图配置留空跟随 AI 配置。"""
        ai = dict(self.cfg.get("ai") or {})
        ic = dict(self.cfg.get("ai_image") or {})
        for k in ("base_url", "api_key", "model"):
            if p.get(k):
                ic[k] = str(p[k]).strip()
        base = (ic.get("base_url") or ai.get("base_url") or "").rstrip("/")
        key = ic.get("api_key") or ai.get("api_key")
        model = ic.get("model")
        if not (base and key and model):
            raise RuntimeError("未配置生图：点顶栏「⚙ 设置」填写生图模型"
                               "（API 地址/Key 可留空跟随 AI 配置）")
        prompt = str(p.get("prompt") or "").strip()
        if not prompt:
            raise RuntimeError("请先输入画面描述")
        import requests as _rq
        r = _rq.post(base + "/images/generations",
                     headers={"Authorization": "Bearer %s" % key},
                     json={"model": model, "prompt": prompt,
                           "size": p.get("size") or "1024x1024",
                           "response_format": "b64_json"},
                     timeout=(15, 300))
        if r.status_code != 200:
            raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:200]))
        d = (r.json().get("data") or [{}])[0]
        b64 = d.get("b64_json")
        if not b64 and d.get("url"):   # 部分服务只回 URL，落地成字节再上传
            import base64 as _b
            g = _rq.get(d["url"], timeout=(15, 120))
            if g.status_code != 200:
                raise RuntimeError("生图结果下载失败 HTTP %s" % g.status_code)
            b64 = _b.b64encode(g.content).decode()
        if not b64:
            raise RuntimeError("生图返回为空")
        return {"b64": b64, "mime": "image/png"}

    def rpc_cfg_get(self, _p):
        return {"mods": self.cfg.get("mods", [])}

    def rpc_cfg_save(self, p):
        mods = p.get("mods") or []
        seen = set()
        for m in mods:
            for k in ("id", "project_dir", "resource_keyword"):
                if not str(m.get(k) or "").strip():
                    raise RuntimeError("存在缺少 %s 的映射" % k)
            if m["id"] in seen:
                raise RuntimeError("显示名重复: %s" % m["id"])
            seen.add(m["id"])
        self.cfg["mods"] = mods
        core.save_config(self.cfg)
        self.js_log("[配置] 本地映射已保存（%d 项）" % len(mods))
        return {"local": self._local_map()}

    def rpc_open_official(self, p):
        name = p.get("name")
        rid = self._rid(name)
        page = self.eng._ctx.new_page()
        page.goto("https://mcdev.webapp.163.com/#/pe/edit/%s" % rid)
        return {"ok": True}

    # ---------- 应用信息 / 检查更新 / 登录门支撑 ----------
    def rpc_app_info(self, _p):
        return {"version": APP_VERSION, "repo": REPO_URL,
                "phone": self.web_url() if self.web_token else None,
                "lan_only": bool(self.cfg.get("web_lan", True))}

    def rpc_check_update(self, _p):
        status, _, data = _http_get(
            "https://api.github.com/repos/InvisibleGuardian007/ModPublisher"
            "/releases/latest")
        j = json.loads(data.decode("utf-8")) if status == 200 else {}
        tag = j.get("tag_name") or ""
        asset = next((a for a in (j.get("assets") or [])
                      if str(a.get("name", "")).endswith(".exe")), None)

        def _vn(t):
            return [int(x) for x in re.findall(r"\d+", t)[:3]] or [0]
        has = bool(tag) and _vn(tag) > _vn(APP_VERSION) and asset is not None
        return {"current": APP_VERSION, "latest": tag or "(未知)",
                "has_update": has,
                "asset": {"name": (asset or {}).get("name"),
                          "url": (asset or {}).get("browser_download_url"),
                          "size": (asset or {}).get("size"),
                          "digest": (asset or {}).get("digest", "")} or None,
                "url": REPO_URL + "/releases/latest"}

    def rpc_do_update(self, _p):
        """热更新：下载最新 Release 的 exe → 校验 → 换文件 → 自动重启。
        Windows 运行中不能覆盖自身，用「改名旧的→移入新的→拉起新进程」技巧。"""
        import hashlib
        if not getattr(sys, "frozen", False):
            raise RuntimeError("开发模式不支持热更新：请 git pull 后重跑")
        info = self.rpc_check_update({})
        if not info["has_update"]:
            return {"restarting": False, "reason": "已是最新版本"}
        asset = info["asset"]
        exe = Path(sys.executable).resolve()
        tmp = exe.parent / (exe.name + ".new")
        tag = info["latest"]

        def prog(frac, msg):
            self.ui_event("update_progress",
                          {"frac": frac, "msg": msg,
                           "title": "下载更新 %s" % tag})

        self.js_log("[更新] 开始下载 %s …" % tag)

        def _pc(frac, got, total):
            prog(frac, ("%.1f / %.1f MB" % (got / 1048576, total / 1048576))
                 if total else ("已下载 %.1f MB" % (got / 1048576)))

        status, _, data = _http_get(asset["url"], progress=_pc)
        if status != 200:
            raise RuntimeError("下载失败 HTTP %s" % status)
        prog(1.0, "校验中…")
        digest = str(asset.get("digest") or "")
        if digest.startswith("sha256:"):
            if hashlib.sha256(data).hexdigest() != digest[7:].strip():
                raise RuntimeError("SHA256 校验失败，已取消更新"
                                   "（文件不完整或被篡改）")
        elif asset.get("size") and abs(len(data) - asset["size"]) > 4096:
            raise RuntimeError("大小校验失败，已取消更新")
        with open(tmp, "wb") as f:
            f.write(data)
        self.js_log("[更新] 校验通过，准备重启安装…")
        self.ui_event("update_progress",
                      {"frac": None, "msg": "正在重启安装…", "title": "更新"})

        def _install():
            old = exe.parent / (exe.name + ".old")
            try:
                os.replace(exe, old)      # 运行中的 exe 允许改名
            except Exception:
                pass
            try:
                os.replace(tmp, exe)
            except Exception:
                try:
                    os.replace(old, exe)  # 回滚，保住当前可用版本
                except Exception:
                    pass
                raise
            os.chdir(exe.parent)
            subprocess.Popen([str(exe)])
            os._exit(0)
        threading.Timer(1.0, _install).start()   # 留出 RPC 响应返回时间
        return {"restarting": True, "version": tag}

    def rpc_app_install(self, _p):
        """应用内自安装：复制到 LOCALAPPDATA/Programs、创建桌面/开始菜单
        快捷方式、注册「应用和功能」卸载入口。"""
        import shutil
        if not getattr(sys, "frozen", False):
            raise RuntimeError("开发模式无需安装：源码直接跑 启动发布器.bat")
        # 已用安装程序装过（Inno 低权限写入 HKCU，键名带 _is1 后缀）→ 不重复
        import winreg
        try:
            winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                r"\{A7C3E1D0-6F5B-4E0A-9C7D-1E2F3A4B5C6D}_is1")
            return {"installed": True, "exe": "",
                    "steps": ["已通过安装程序安装，快捷方式与卸载入口均已就绪"]}
        except OSError:
            pass
        exe = Path(sys.executable).resolve()
        tdir = Path(os.environ.get("LOCALAPPDATA", exe.parent)) / "Programs" / "ModPublisher"
        tdir.mkdir(parents=True, exist_ok=True)
        steps = []
        dst = tdir / exe.name
        if exe.parent.resolve() != tdir.resolve():
            try:
                shutil.copy2(exe, dst)
                steps.append("程序已复制到 %s" % tdir)
            except Exception as e:
                if not dst.exists():
                    raise RuntimeError("复制程序失败：%s" % e)
                steps.append("目标已有同名程序，跳过复制")
        exe_ref = dst if dst.exists() else exe
        unins = tdir / "卸载ModPublisher.ps1"
        unins.write_text(
            "$exe='%s'\n"
            "Get-Process | Where-Object {$_.Path -eq $exe} | Stop-Process -Force\n"
            "Start-Sleep 1\n"
            "Remove-Item -Recurse -Force '%s'\n"
            "Remove-Item -LiteralPath '%s' -ErrorAction SilentlyContinue\n"
            % (exe_ref, tdir,
               r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ModPublisher"),
            encoding="utf-8")
        ps = r'''
$ws = New-Object -ComObject WScript.Shell
$dt = [Environment]::GetFolderPath('Desktop')
$l1 = $ws.CreateShortcut("$dt\网易模组发布器.lnk")
$l1.TargetPath = "{exe}"; $l1.WorkingDirectory = "{dir}"; $l1.Save()
$sm = [Environment]::GetFolderPath('StartMenu') + "\Programs\网易模组发布器"
New-Item -ItemType Directory -Force -Path $sm | Out-Null
$l2 = $ws.CreateShortcut("$sm\网易模组发布器.lnk")
$l2.TargetPath = "{exe}"; $l2.WorkingDirectory = "{dir}"; $l2.Save()
$k = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ModPublisher"
New-Item -Force -Path $k | Out-Null
Set-ItemProperty $k -Name DisplayName -Value "网易模组发布器"
Set-ItemProperty $k -Name DisplayVersion -Value "{ver}"
Set-ItemProperty $k -Name DisplayIcon -Value "{exe}"
Set-ItemProperty $k -Name InstallLocation -Value "{dir}"
Set-ItemProperty $k -Name UninstallString -Value 'powershell -ExecutionPolicy Bypass -File "{unins}"'
Set-ItemProperty $k -Name NoModify -Value 1 -Type DWord
Set-ItemProperty $k -Name NoRepair -Value 1 -Type DWord
'''.format(exe=exe_ref, dir=tdir, ver=APP_VERSION, unins=unins)
        f = Path(tempfile.gettempdir()) / ("mp_install_%d.ps1" % time.time_ns())
        f.write_text(ps, encoding="utf-8-sig")   # BOM 保证 PS5.1 正确读中文
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(f)],
                capture_output=True, text=True, timeout=60,
                creationflags=core.CREATE_NO_WINDOW)
        finally:
            try:
                f.unlink()
            except Exception:
                pass
        if r.returncode != 0:
            raise RuntimeError("创建快捷方式失败：%s" % (r.stderr or r.stdout)[:200])
        steps.append("桌面/开始菜单快捷方式已创建")
        steps.append("已注册到「应用和功能」，可随时卸载")
        self.js_log("[安装] " + "；".join(steps))
        return {"steps": steps, "exe": str(exe_ref), "installed": True}

    # ---------- 高层操作（CLI / HTTP API 共用，均在引擎线程执行） ----------
    def h_set(self, name, changes):
        rid = self._rid(name)

        def job():
            detail = self.api.detail(rid)
            detail.update(changes)
            body = PA.build_update_body(detail, dict(changes))
            self.api.update_item(rid, body)
            return {"updated": sorted(changes)}
        return self.submit(job)

    def h_set_pc(self, name, html):
        """PC 详情信息 = sync_item_info.info（平台与 PE 详情是两份独立富文本）。"""
        rid = self._rid(name)

        def job():
            detail = self.api.detail(rid)
            si = detail.get("sync_item_info")
            si = dict(si) if isinstance(si, dict) else {}
            html = PA.sanitize_detail_html(html)
            PA.validate_detail_html(html, budget=PA.PC_DETAIL_BUDGET)
            si["info"] = html
            detail["sync_item_info"] = si
            body = PA.build_update_body(detail, {"sync_item_info": si})
            self.api.update_item(rid, body)
            return {"pc_len": len(html), "pc_imgs": html.count("<img")}
        return self.submit(job)

    def h_add_image(self, name, img_path, mime=None):
        img = Path(img_path)
        mime = mime or ("image/png" if img.suffix.lower() == ".png" else "image/jpeg")
        rid = self._rid(name)

        def job():
            info = self.api.upload("image", img, mime)
            url = json.loads(info["body"]).get("url")
            detail = self.api.detail(rid)
            key = ("pe_game_introduction"
                   if "<p>" in (detail.get("pe_game_introduction") or "") else "info")
            html = detail.get(key) or ""
            if not ("<p>" in html or "<img" in html):
                html = ""
            html = html + '<p><img src="%s"></p>' % url
            PA.validate_detail_html(html)  # 超限会静默截断吞图，先失败
            detail[key] = html
            body = PA.build_update_body(detail, {key: html})
            self.api.update_item(rid, body)
            return {"image": url, "detail_key": key}
        return self.submit(job)

    def h_publish(self, name, zip_=True, boost=True, submit=False, note=None):
        mod = self._mod(name)
        rid = self._rid(name)
        p = {"name": name, "zip": zip_, "boost": boost,
             "item_name": None, "update_summary": note,
             "activity_desc": None, "pc_intro": None, "detail_html": None}

        def job():
            detail = self.api.detail(rid)
            r = self._api_publish(rid, mod, detail, p, name=name)
            if submit:
                self.api.apply_review(rid, note or "")
                r["submitted"] = True
            return r
        return self.submit(job)

    def h_submit(self, name, note=""):
        rid = self._rid(name)
        return self.submit(lambda: self.api.apply_review(rid, note))

    # ---------- 本地 Agent HTTP API + 手机端 Web ----------
    def serve_http(self, port=8765):
        import http.server
        import socketserver
        import queue as _q
        import urllib.parse as _up
        import uuid as _uuid
        host = self
        host.web_token = _uuid.uuid4().hex[:8]
        host.http_port = port
        try:
            import socket as _s
            _s0 = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
            _s0.connect(("8.8.8.8", 80))
            host.lan_ip = _s0.getsockname()[0]
            _s0.close()
        except Exception:
            pass

        def _tok_ok(qs, headers):
            t = _up.parse_qs(qs).get("token", [""])[0]
            return t == host.web_token or headers.get("X-Token") == host.web_token

        class H(http.server.BaseHTTPRequestHandler):
            def _send(self, obj, code=200):
                b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _loopback_only(self):
                return self.client_address[0] in ("127.0.0.1", "::1")

            def do_GET(self):
                u = _up.urlparse(self.path)
                if u.path == "/favicon.ico":
                    fp = Path(__file__).resolve().parent / "docs" / "icon.ico"
                    if not fp.exists() and getattr(sys, "frozen", False):
                        fp = (Path(getattr(sys, "_MEIPASS",
                              Path(sys.executable).parent)) / "docs" / "icon.ico")
                    if fp.exists():
                        b = fp.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/x-icon")
                        self.send_header("Content-Length", str(len(b)))
                        self.end_headers()
                        self.wfile.write(b)
                    else:
                        self._send({"ok": False}, 404)
                    return
                if u.path == "/ui":
                    # 手机端入口：token 防护（同机打开无 token 也放行）
                    if not (_tok_ok(u.query, self.headers)
                            or self._loopback_only()):
                        b = ("<meta charset=utf-8><body style='font-family:sans-serif;"
                             "background:#12141a;color:#e8ebf4;display:flex;"
                             "align-items:center;justify-content:center;height:96vh'>"
                             "<p>token 无效：请从发布器「⚙ 设置」复制完整手机端链接"
                             "</p></body>").encode("utf-8")
                        self.send_response(401)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(b)))
                        self.end_headers()
                        self.wfile.write(b)
                        return
                    try:
                        b = UI_FILE.read_bytes()
                    except Exception:
                        b = "ui.html 缺失".encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
                if u.path == "/events":
                    if not (_tok_ok(u.query, self.headers)
                            or self._loopback_only()):
                        return self._send({"ok": False, "error": "token 无效"}, 401)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    q = _q.Queue()
                    host._sse.append(q)
                    try:
                        while True:
                            try:
                                m = q.get(timeout=15)
                            except Exception:
                                m = None
                            if m is not None:
                                self.wfile.write(("data: " + json.dumps(
                                    m, ensure_ascii=False) + "\n\n")
                                    .encode("utf-8"))
                            else:
                                self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                    except Exception:
                        pass
                    finally:
                        try:
                            host._sse.remove(q)
                        except Exception:
                            pass
                    return
                if self.path == "/ping":
                    self._send({"ok": True, "app": "网易模组发布器",
                                "version": APP_VERSION})
                else:
                    self._send({"ok": False, "error": "未知GET " + self.path}, 404)

            def do_POST(self):
                try:
                    u = _up.urlparse(self.path)
                    ln = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(ln) or b"{}")
                    cmd = u.path.strip("/")
                    if cmd == "rpc":   # 手机端通用 RPC 桥（token 防护）
                        if not _tok_ok(u.query, self.headers):
                            return self._send({"ok": False, "error": "token 无效"},
                                              401)
                        action = str(payload.get("action") or "")
                        fn = getattr(host, "rpc_" + action, None)
                        if not callable(fn) or action.startswith("_"):
                            return self._send({"ok": False,
                                               "error": "未知RPC " + action}, 404)
                        out = host.submit(
                            lambda: fn(payload.get("payload") or {}), timeout=900)
                        return self._send({"ok": True, "data": out})
                    if not self._loopback_only():
                        return self._send({"ok": False, "error": "仅限本机调用"},
                                          403)
                    # 自愈：浏览器窗口没了就先重开（引擎存活时是廉价检查）
                    host.submit(lambda: host.ensure(), timeout=120)

                    def boot():
                        return host.rpc_boot({})

                    if cmd == "list":
                        self._send({"ok": True, "data": host.submit(boot)})
                    elif cmd == "read":
                        self._send({"ok": True, "data": host.submit(
                            lambda: host.rpc_read_item({"name": payload["name"]}))})
                    elif cmd == "set":
                        self._send({"ok": True, "data": host.h_set(
                            payload["name"], payload.get("changes") or {})})
                    elif cmd == "add-image":
                        self._send({"ok": True, "data": host.h_add_image(
                            payload["name"], payload["image"])})
                    elif cmd == "publish":
                        self._send({"ok": True, "data": host.h_publish(
                            payload["name"], zip_=payload.get("zip", True),
                            boost=payload.get("boost", True),
                            submit=payload.get("submit", False),
                            note=payload.get("note"))})
                    elif cmd == "submit":
                        self._send({"ok": True, "data": host.h_submit(
                            payload["name"], payload.get("note") or "")})
                    elif cmd == "set-pc":
                        self._send({"ok": True, "data": host.h_set_pc(
                            payload["name"], payload["html"])})
                    elif cmd == "open":
                        def _open():
                            r = host.rpc_open_official(payload)
                            try:  # 把新开的官方编辑页带到前台
                                cands = [pg2 for pg2 in host.eng._ctx.pages
                                         if "mcdev.webapp.163.com" in (pg2.url or "")]
                                if cands:
                                    cands[-1].bring_to_front()
                            except Exception:
                                pass
                            return r
                        self._send({"ok": True, "data": host.submit(_open)})
                    else:
                        self._send({"ok": False, "error": "未知命令 " + cmd}, 404)
                except Exception as e:
                    self._send({"ok": False, "error": str(e)}, 500)

            def log_message(self, *a):
                pass

        class S(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        bind_ip = "0.0.0.0" if host.cfg.get("web_lan", True) else "127.0.0.1"
        srv = S((bind_ip, port), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        if bind_ip == "0.0.0.0":
            host.js_log("[手机端] 同一局域网手机浏览器打开：%s" % host.web_url())
        return port

    # ---------- 工具 ----------
    def _rid(self, name):
        for n, rid in self.rows:
            if n == name:
                return rid
        return None

    def _mod(self, name):
        for m in self.cfg["mods"]:
            kw = m.get("resource_keyword") or ""
            if kw and kw in name:
                return m
        raise RuntimeError("未配置本地项目: %s" % name)


# ================= MCP 服务器（--mcp，stdio JSON-RPC 2.0，供 Agent 即插即用） =================
MCP_TOOLS = [
    {"name": "list_works",
     "description": "列出网易开发者平台账号下全部PE作品（状态/发布时间/本地映射/建议名称与纪要）",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "read_item",
     "description": "读取某作品全部字段（165键）+ 详情HTML + 图片槽位/视频/攻略",
     "inputSchema": {"type": "object", "required": ["name"],
                     "properties": {"name": {"type": "string",
                       "description": "作品名（list_works 返回的 name）"}}}},
    {"name": "set_fields",
     "description": "修改作品任意平台字段并保存（值均为字符串：列表/对象传JSON字面量，布尔传true/false）",
     "inputSchema": {"type": "object", "required": ["name", "changes"],
                     "properties": {"name": {"type": "string"},
                       "changes": {"type": "object",
                         "description": '如 {"item_name":"新名称","update_summary":"26.11.8更新：…"}'}}}},
    {"name": "set_pc_detail",
     "description": "设置PC详情富文本（sync_item_info.info，与PE详情相互独立；上限1000字）",
     "inputSchema": {"type": "object", "required": ["name", "html"],
                     "properties": {"name": {"type": "string"},
                       "html": {"type": "string"}}}},
    {"name": "add_image",
     "description": "上传本地图片并追加到PE详情末尾",
     "inputSchema": {"type": "object", "required": ["name", "image"],
                     "properties": {"name": {"type": "string"},
                       "image": {"type": "string", "description": "图片绝对路径"}}}},
    {"name": "publish",
     "description": "打包本地项目→直传→update保存；会重生成manifest uuid并把版本号改为当天日期",
     "inputSchema": {"type": "object", "required": ["name"],
                     "properties": {"name": {"type": "string"},
                       "zip": {"type": "boolean", "description": "默认true=打包上传新包"},
                       "boost": {"type": "boolean", "description": "默认true=提升版本"},
                       "submit": {"type": "boolean",
                         "description": "默认false；true=保存后一并提交审核"},
                       "note": {"type": "string", "description": "PE更新纪要"}}}},
    {"name": "submit_review",
     "description": "提交审核（不可逆动作，必须先经用户确认）",
     "inputSchema": {"type": "object", "required": ["name"],
                     "properties": {"name": {"type": "string"},
                       "note": {"type": "string"}}}},
    {"name": "open_official",
     "description": "在发布器窗口打开该作品的官方编辑页",
     "inputSchema": {"type": "object", "required": ["name"],
                     "properties": {"name": {"type": "string"}}}},
]


def _api_alive():
    import urllib.request as _u
    try:
        with _u.urlopen("http://127.0.0.1:8765/ping", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _api_call(path, payload, timeout=600):
    import urllib.request as _u
    req = _u.Request("http://127.0.0.1:8765/" + path,
                     data=json.dumps(payload).encode("utf-8"),
                     headers={"Content-Type": "application/json"})
    with _u.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _ensure_publisher():
    """MCP 是常驻发布器的轻量代理；发布器未运行时拉起一个再继续。"""
    if _api_alive():
        return
    if getattr(sys, "frozen", False):
        subprocess.Popen([sys.executable], creationflags=core.CREATE_NO_WINDOW)
    else:
        raise RuntimeError("发布器未运行：请先执行 启动发布器.bat（源码模式不自动拉起）")
    for _ in range(60):
        time.sleep(0.5)
        if _api_alive():
            return
    raise RuntimeError("发布器启动超时（Agent API :8765 未就绪）")


def mcp_call(tool, args):
    _ensure_publisher()
    name = args.get("name") or ""
    if tool == "list_works":
        return _api_call("list", {})["data"]
    if tool == "read_item":
        return _api_call("read", {"name": name})["data"]
    if tool == "set_fields":
        return _api_call("set", {"name": name,
                                 "changes": args.get("changes") or {}})
    if tool == "set_pc_detail":
        return _api_call("set-pc", {"name": name, "html": args.get("html") or ""})
    if tool == "add_image":
        return _api_call("add-image", {"name": name, "image": args.get("image")})
    if tool == "publish":
        return _api_call("publish", {"name": name,
                                     "zip": bool(args.get("zip", True)),
                                     "boost": bool(args.get("boost", True)),
                                     "submit": bool(args.get("submit", False)),
                                     "note": args.get("note")})
    if tool == "submit_review":
        return _api_call("submit", {"name": name, "note": args.get("note") or ""})
    if tool == "open_official":
        return _api_call("open", {"name": name})
    raise RuntimeError("未知工具: %s" % tool)


def run_mcp():
    """stdio MCP：换行分隔 JSON-RPC 2.0。Agent 配置示例见 README「Agent 接口」。"""
    def send(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        rid = req.get("id")
        method = req.get("method") or ""
        try:
            if method == "initialize":
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "protocolVersion": (req.get("params") or {}).get(
                        "protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "netease-mod-publisher",
                                   "version": APP_VERSION}}})
            elif method == "ping":
                send({"jsonrpc": "2.0", "id": rid, "result": {}})
            elif method == "tools/list":
                send({"jsonrpc": "2.0", "id": rid,
                      "result": {"tools": MCP_TOOLS}})
            elif method == "tools/call":
                params = req.get("params") or {}
                try:
                    out = mcp_call(params.get("name") or "",
                                   params.get("arguments") or {})
                    send({"jsonrpc": "2.0", "id": rid, "result": {"content": [
                        {"type": "text",
                         "text": json.dumps(out, ensure_ascii=False, indent=1)}]}})
                except Exception as e:
                    send({"jsonrpc": "2.0", "id": rid, "result": {
                        "content": [{"type": "text", "text": "错误: %s" % e}],
                        "isError": True}})
            elif rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "error":
                      {"code": -32601, "message": "未知方法 %s" % method}})
        except Exception as e:
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "error":
                      {"code": -32603, "message": str(e)}})
    return 0


# ================= Agent CLI（无界面自动化） =================
def run_cmd(argv):
    """agent 直接驱动（优先复用常驻 exe 的活会话，否则本地无头起引擎）：
    --cmd list | read <作品名> | set <作品名> --json '{..}'
      | set-pc <作品名> --json '"<p>..PC详情HTML..</p>"'
      | add-image <作品名> --img <路径>
      | publish <作品名> [--no-zip] [--no-boost] [--submit] [--note 文本]
      | submit <作品名> [--note 文本]
    """
    import argparse
    import urllib.request as _u
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True)
    ap.add_argument("pos", nargs="*")
    ap.add_argument("--json")
    ap.add_argument("--img")
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--no-boost", action="store_true")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--note")
    a = ap.parse_args(argv)
    name = a.pos[0] if a.pos else None

    def emit(out):
        text = json.dumps(out, ensure_ascii=False, indent=1)
        try:
            (core.APP_DIR / "cli_out.json").write_text(text, encoding="utf-8")
        except Exception:
            pass
        if sys.stdout:
            print(text)
        return 0 if out.get("ok") else 1

    # 1) 常驻实例可用 → 走它的活会话
    endpoint = {"list": ("list", {}), "read": ("read", {"name": name}),
                "set": ("set", {"name": name, "changes": json.loads(a.json or "{}")}),
                "set-pc": ("set-pc", {"name": name,
                                      "html": json.loads(a.json or '""')}),
                "add-image": ("add-image", {"name": name, "image": a.img}),
                "publish": ("publish", {"name": name, "zip": not a.no_zip,
                                        "boost": not a.no_boost,
                                        "submit": a.submit, "note": a.note}),
                "submit": ("submit", {"name": name, "note": a.note or ""})}.get(a.cmd)
    if not endpoint:
        return emit({"ok": False, "error": "未知命令: %s" % a.cmd})
    path, payload = endpoint
    try:
        with _u.urlopen("http://127.0.0.1:8765/ping", timeout=2) as r:
            alive = r.status == 200
    except Exception:
        alive = False
    if alive:
        req = _u.Request("http://127.0.0.1:8765/" + path,
                         data=json.dumps(payload).encode("utf-8"),
                         headers={"Content-Type": "application/json"})
        try:
            with _u.urlopen(req, timeout=600) as r:
                return emit(json.loads(r.read().decode("utf-8")))
        except Exception as e:
            detail = ""
            if hasattr(e, "read"):
                try:
                    detail = e.read().decode("utf-8")[:200]
                except Exception:
                    pass
            return emit({"ok": False, "error": "%s %s" % (e, detail)})

    # 2) 回退：本地无头引擎（附加优先：已有窗口就复用它，无窗口才拉起无头实例）
    cfg = core.load_config()
    cfg["headless_browser"] = True
    host = Host(cfg)
    try:
        host.start()
        S = host.submit
        S(lambda: host.rpc_boot({}))  # rid 映射 + 登录校验
        if getattr(host, "_boot_err", None):
            raise RuntimeError(host._boot_err)
        data = {"list": lambda: S(lambda: host.rpc_boot({})),
                "read": lambda: S(lambda: host.rpc_read_item({"name": name})),
                "set": lambda: host.h_set(name, json.loads(a.json or "{}")),
                "add-image": lambda: host.h_add_image(name, a.img),
                "publish": lambda: host.h_publish(
                    name, zip_=not a.no_zip, boost=not a.no_boost,
                    submit=a.submit, note=a.note),
                "submit": lambda: host.h_submit(name, a.note or "")}[a.cmd]()
        return emit({"ok": True, "data": data})
    except Exception as e:
        return emit({"ok": False, "error": str(e)})
    finally:
        try:
            host.submit(lambda: host.eng.close(), timeout=15)
        except Exception:
            pass


def _http_get(url, headers=None, progress=None, timeout=(15, 300)):
    """GET → (status, headers, bytes)。requests 流式优先；
    证书校验失败（VPN/代理自签 CA 环境）退回系统证书栈（urllib），
    保证热更新在任何网络环境下可用。"""
    import requests as _rq
    try:
        r = _rq.get(url, stream=True, headers=headers or {}, timeout=timeout)
        total = int(r.headers.get("Content-Length") or 0)
        buf = bytearray()
        got = 0
        for chunk in r.iter_content(262144):
            if chunk:
                buf.extend(chunk)
                got += len(chunk)
                if progress and total:
                    progress(min(1.0, got / total), got, total)
        return r.status_code, dict(r.headers), bytes(buf)
    except _rq.exceptions.SSLError:
        pass
    import urllib.request as _u
    req = _u.Request(url, headers=headers or {})
    with _u.urlopen(req, timeout=timeout[1]) as g:
        total = int((g.headers or {}).get("Content-Length") or 0)
        buf = bytearray()
        got = 0
        while True:
            chunk = g.read(262144)
            if not chunk:
                break
            buf.extend(chunk)
            got += len(chunk)
            if progress and total:
                progress(min(1.0, got / total), got, total)
        return g.status, dict(g.headers or {}), bytes(buf)


def main():
    # 热更新遗留清理：上次自更新留下的旧/半成品文件
    if getattr(sys, "frozen", False):
        _exe = Path(sys.executable)
        for _left in (_exe.parent / (_exe.name + ".old"),
                      _exe.parent / (_exe.name + ".new")):
            try:
                _left.unlink(missing_ok=True)
            except Exception:
                pass
    if "--selftest" in sys.argv:
        out = core.APP_DIR / "selftest.txt"
        try:
            cfg = core.load_config()
            lines = ["config ok, mods=%d" % len(cfg["mods"])]
            for m in cfg["mods"]:
                info = core.mod_info(m)
                lines.append("%s ver=%s count=%s name=%r" % (
                    m["id"], info["version"], info["count"], info["name_suggest"]))
            out.write_text(chr(10).join(lines), encoding="utf-8")
        except Exception as e:
            out.write_text("FAIL: %r" % e, encoding="utf-8")
        return
    argv = sys.argv[1:]
    if "--mcp" in argv:
        sys.exit(run_mcp())
    if "--cmd" in argv:
        sys.exit(run_cmd(argv))
    import ctypes
    import urllib.request as _u

    def box(msg, title="网易模组发布器"):
        try:  # 10 秒自动关闭的提示框（重复实例/启动失败不至于卡死）
            ctypes.windll.user32.MessageBoxTimeoutW(
                0, msg, title, 0, 0, 10000)
        except Exception:
            pass

    # 重复实例检测：Agent API 已在线 → 说明发布器已在运行（ping 重试防抖）
    try:
        alive = False
        for _ in range(2):
            try:
                with _u.urlopen("http://127.0.0.1:8765/ping", timeout=2) as r:
                    if r.status == 200:
                        alive = True
                        break
            except Exception:
                time.sleep(0.6)
        if alive:
            focus_publisher_window(["http://127.0.0.1:8765/ui", UI_FILE.as_uri()])
            box("发布器已在运行中，已为你调出发布器窗口。\n\n"
                "Agent API: http://127.0.0.1:8765")
            return
    except Exception:
        pass

    host = Host(core.load_config())
    try:   # HTTP 先起：--app 窗口直接指向本地 UI（favicon 即应用图标）
        port = host.serve_http(8765)
        host.cfg["app_url"] = host.web_url()
        host.js_log("[Agent API] http://127.0.0.1:%d （list/read/set/set-pc/add-image/publish/submit）" % port)
    except Exception as e:
        host.js_log("[Agent API] 启动失败: %s" % e)
    try:
        host.start()
    except Exception as e:
        box("启动失败：%s\n\n常见原因：已有另一个发布器实例在运行并占用登录数据"
            "（请先关闭它再打开）。" % e)
        return
    if "--reside" in sys.argv:
        # 常驻模式（Agent 用）：窗口关闭不退出进程，HTTP API 常驻，
        # 下次接口调用自动重开浏览器窗口。Ctrl+C 退出。
        host.exit_on_close = False
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        os._exit(0)
    # 窗口（Edge 本体）关闭 → 结束引擎并带走全部自有 Edge 窗口（无僵尸）
    host._closed.wait()
    try:
        host.submit(lambda: host.eng.close(kill=True), timeout=10)
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
