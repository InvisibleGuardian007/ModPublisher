# -*- coding: utf-8 -*-
"""网易模组发布器 v11 —— 单窗口：窗口即 Edge 本体，界面 ui.html，Python 引擎
经 Playwright 绑定提供 RPC；引擎线程空闲时泵消息保证绑定实时可达。"""
import ctypes
import json
import os
import re
import sys
import subprocess
import threading
import time
from pathlib import Path

import publish_api as PA
import publish_core as core

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

if getattr(sys, "frozen", False):
    UI_FILE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "ui.html"
else:
    UI_FILE = Path(__file__).resolve().parent / "ui.html"


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
        """引擎线程 → UI 页面推送（进度等）。"""
        if self._ui_event:
            try:
                self._ui_event(kind, json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass

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
        # 会话恢复（崩溃/强杀后 Edge 会把上次标签原样带回）可能造成重复 UI 页，先归一
        api_reused = self._dedupe_pages(ctx)
        if not api_reused:
            try:
                self.api_page.goto("https://mcdev.webapp.163.com/",
                                   wait_until="domcontentloaded", timeout=30000)
                self.api_page.wait_for_timeout(3500)
            except Exception:
                pass
        # 主页面 = 自制复刻界面（结构同官方编辑页，体验优化+底部自动化）
        self.page.goto(UI_FILE.as_uri(), wait_until="domcontentloaded")
        self._ui_event = lambda kind, pj: self.page.evaluate(
            "([k,j])=>window.__mpEvent&&window.__mpEvent(k,j)", [kind, pj])
        try:
            self.page.bring_to_front()
        except Exception:
            pass
        self.api.set_context(ctx, page=self.api_page)
        try:
            ctx.on("close", lambda _c: self._on_ctx_closed())
        except Exception:
            pass
        return self.eng

    def _dedupe_pages(self, ctx):
        """崩溃/强杀后 Edge 会话恢复会把上次的 ui.html 标签带回（context 级绑定对恢复
        标签同样生效，会重复引导 RPC），UI 页只保留一个；停靠页若仍活着则复用。
        返回 api_page 是否复用（复用时不再重复 goto 平台域）。"""
        ui_pages = [pg for pg in ctx.pages
                    if (pg.url or "").startswith(UI_FILE.as_uri())]
        for pg in ui_pages[1:]:
            try:
                pg.close()
            except Exception:
                pass
        self.page = ui_pages[0] if ui_pages else (
            ctx.pages[0] if ctx.pages else ctx.new_page())
        ap = self.api_page
        try:
            if ap is not None and not ap.is_closed() \
                    and "mcdev.webapp.163.com" in (ap.url or ""):
                return True
        except Exception:
            pass
        self.api_page = ctx.new_page()
        return False

    def _on_ctx_closed(self):
        """普通模式：窗口关 = 进程退出（否则僵尸进程占 8765，下次启动弹『已在运行中』）；
        --reside 常驻模式：不退出，下次接口调用自动重开。"""
        if self.exit_on_close:
            self._closed.set()
            print("[引擎] 浏览器窗口已关闭，进程退出", flush=True)
        else:
            print("[引擎] 浏览器窗口已关闭；下次接口调用自动重开", flush=True)

    def _back_to_ui(self):
        try:
            self.page.goto(UI_FILE.as_uri(), wait_until="domcontentloaded")
        except Exception:
            pass

    def js_log(self, msg):
        def push():
            try:
                self.page.evaluate(
                    "s=>{const l=document.getElementById('log');"
                    "if(l){l.textContent+=s+'\n';l.scrollTop=1e9}}", msg)
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
            except Exception as e:
                self.js_log("[API] 详情失败转浏览器: %s" % e)
        # 浏览器兜底
        cur = self.eng.read_current(name)
        cur.pop("detail_plain", None)
        return cur

    def rpc_login(self, _p):
        self.ensure()
        ok = self.eng.open_login(timeout_s=600)
        if ok:
            try:
                self.api.user_info()
            except Exception:
                ok = False
        self._back_to_ui()
        return {"ok": bool(ok)}

    def rpc_upload_image(self, p):
        import base64
        import tempfile
        raw = base64.b64decode(p["b64"])
        suffix = ".png"
        if "jpeg" in (p.get("mime") or "") or "jpg" in (p.get("mime") or ""):
            suffix = ".jpg"
        f = Path(tempfile.gettempdir()) / ("mp_img_%d%s" % (time.time(), suffix))
        f.write_bytes(raw)
        try:
            info = self.api.upload("image", f, p.get("mime") or "image/png")
            return json.loads(info["body"]).get("url")
        finally:
            try:
                f.unlink()
            except Exception:
                pass

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
                return self._api_publish(rid, mod, detail, p)
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

    def _api_publish(self, rid, mod, detail, p):
        changes = dict(p.get("changes") or {})  # 全字段：界面脏值直接生效
        if p.get("item_name"):
            changes["item_name"] = p["item_name"]
        if p.get("update_summary"):
            changes["update_summary"] = p["update_summary"][:200]
            changes["current_change_log"] = changes["update_summary"]
        if p.get("activity_desc"):
            changes["activity_desc"] = p["activity_desc"]
        if p.get("pc_intro"):
            si = detail.get("sync_item_info")
            si = si if isinstance(si, dict) else {}
            si["brief"] = p["pc_intro"]
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
        r = self._verify_publish(rid, detail, changes, det_key, zip_name)
        r.setdefault("zip", zip_name or ((detail.get("res") or [{}])[0]
                                         .get("res_name") if detail.get("res") else None))
        return r

    def _verify_publish(self, rid, old_detail, changes, key, zip_name):
        """update 后立即回读验证：平台对超预算详情**静默截断吞图**、包替换失败均无报错，
        只有回读能发现。异常等 2 秒复查一次（排除读延迟）再判死。
        返回回执（新旧版本号、详情字数/图数、落库包名）。"""
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
                        "zip": got_zip or None}
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


    # ---------- 工具栏 RPC（真平台编辑页上的自动化） ----------
    def _name_of_rid(self, rid):
        if not self.rows:
            self.rpc_boot({})
        for n, r in self.rows:
            if str(r) == str(rid):
                return n
        return None

    def rpc_slot_save(self, p):
        """图片槽位：key=banner(组件ICON) 或 channel:<id>。上传并保存。"""
        import base64
        import tempfile
        rid = self._rid(p["name"])
        tmp = Path(tempfile.gettempdir()) / ("mp_slot_%d.png" % time.time())
        tmp.write_bytes(base64.b64decode(p["b64"]))
        try:
            info = self.api.upload("image", tmp, p.get("mime") or "image/png")
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass
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
                    # 替换槽位：channel_url=上传回执（对齐 McDevManager DTO 形态）
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
        import base64
        import tempfile
        rid = self._rid(p["name"])
        tmp = Path(tempfile.gettempdir()) / ("mp_pcs_%d.png" % time.time())
        tmp.write_bytes(base64.b64decode(p["b64"]))
        try:
            info = self.api.upload("image", tmp, p.get("mime") or "image/png")
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass
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
        import base64
        import tempfile
        rid = self._rid(p["name"])
        up = p.get("video") or {}
        cv = p.get("cover") or {}
        if not up.get("b64"):
            raise RuntimeError("缺少视频文件")

        def tmp_write(b64, suffix):
            f = Path(tempfile.gettempdir()) / ("mp_v%d%s" % (time.time(), suffix))
            f.write_bytes(base64.b64decode(b64))
            return f

        vf = tmp_write(up["b64"], ".mp4")
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
            cf = tmp_write(cv["b64"], ".jpg")
            try:
                cinfo = self.api.upload("image", cf, cv.get("mime") or "image/jpeg")
            finally:
                try:
                    cf.unlink()
                except Exception:
                    pass
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

    def rpc_tb_state(self, p):
        rid = p.get("rid")
        name = self._name_of_rid(rid)
        local = self._local_map().get(name) if name else None
        return {"name": name, "local": local}

    def rpc_tb_pack(self, p):
        rid = p.get("rid")
        name = self._name_of_rid(rid)
        mod = self._mod(name)
        z = core.pack(mod)
        self.js_log("[栏] 打包完成: %s" % os.path.basename(z))
        r = self.eng.apply_and_save(name, {"zip_path": z, "boost": True,
                                           "name": None, "note": None,
                                           "activity": None, "pc_intro": None,
                                           "detail_html": None})
        return {"zip": os.path.basename(z), "saved": True}

    def rpc_tb_publish(self, p):
        rid = p.get("rid")
        name = self._name_of_rid(rid)
        mod = self._mod(name)
        z = core.pack(mod)
        self.js_log("[栏] 打包完成: %s" % os.path.basename(z))
        info = self.api.upload("zip_package", z, "application/zip")
        self.js_log("[栏] 直传完成 sign=%s…" % info["sign"][:10])
        detail = self.api.detail(rid)
        body = PA.build_update_body(detail, {
            "new_res": info, "new_res_name": os.path.basename(z),
            "add_version": True})
        self.api.update_item(rid, body)
        # 同步页面显示：直接刷新编辑页
        try:
            self.page.reload(wait_until="domcontentloaded")
        except Exception:
            pass
        return {"zip": os.path.basename(z), "saved": True}

    def rpc_tb_submit(self, p):
        rid = p.get("rid")
        name = self._name_of_rid(rid)
        self.eng.open_editor(re.escape(name), key=name)
        self.eng.submit()
        return {"ok": True}

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
            r = self._api_publish(rid, mod, detail, p)
            if submit:
                self.api.apply_review(rid, note or "")
                r["submitted"] = True
            return r
        return self.submit(job)

    def h_submit(self, name, note=""):
        rid = self._rid(name)
        return self.submit(lambda: self.api.apply_review(rid, note))

    # ---------- 本地 Agent HTTP API ----------
    def serve_http(self, port=8765):
        import http.server
        import socketserver
        host = self

        class H(http.server.BaseHTTPRequestHandler):
            def _send(self, obj, code=200):
                b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                if self.path == "/ping":
                    self._send({"ok": True, "app": "网易模组发布器"})
                else:
                    self._send({"ok": False, "error": "未知GET " + self.path}, 404)

            def do_POST(self):
                try:
                    ln = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(ln) or b"{}")
                    cmd = self.path.strip("/")
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

        srv = S(("127.0.0.1", port), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
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

    # 2) 回退：本地无头（先清残留实例，避免票据回滚竞态）
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"name='msedge.exe'\" | "
                        "Where-Object { $_.CommandLine -like '*ModPublisher*profile*' } | "
                        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
                        "-ErrorAction SilentlyContinue }"],
                       capture_output=True, timeout=20)
    except Exception:
        pass
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


def main():
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

    # 重复实例检测：Agent API 已在线 → 说明发布器已在运行
    try:
        with _u.urlopen("http://127.0.0.1:8765/ping", timeout=2) as r:
            if r.status == 200:
                box("发布器已在运行中。\n\n如界面被覆盖，请查看任务栏；"
                    "Agent API: http://127.0.0.1:8765")
                return
    except Exception:
        pass

    host = Host(core.load_config())
    try:
        host.start()
    except Exception as e:
        box("启动失败：%s\n\n常见原因：已有另一个发布器实例在运行并占用登录数据"
            "（请先关闭它再打开）。" % e)
        return
    try:
        port = host.serve_http(8765)
        host.js_log("[Agent API] http://127.0.0.1:%d （list/read/set/set-pc/add-image/publish/submit）" % port)
    except Exception as e:
        host.js_log("[Agent API] 启动失败: %s" % e)
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
    # 窗口（Edge 本体）关闭 → 引擎结束 → 进程退出
    host._closed.wait()
    try:
        host.submit(lambda: host.eng.close(), timeout=10)
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
