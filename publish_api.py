# -*- coding: utf-8 -*-
"""网易开发者平台直连 API（端点参考开源项目 McDevManager 的逆向，BNCL-1.0）。
传输层走 Playwright 浏览器上下文的 ctx.request：与内嵌浏览器共享轮换 cookie，
不存在票据竞争。浏览器只用于登录与兜底；所有读写均为显式调用。"""
import base64
import json
import os
import re
import time
from pathlib import Path

BASE = "https://mc-launcher.webapp.163.com/"
UPLOAD_DEFAULT = "https://fp.ps.netease.com/x19/file/new/"


class ApiError(Exception):
    pass


class DetailValidationError(ApiError):
    """详情预检/回读验证失败（转浏览器自动化也救不了，直接中止不兜底）。"""


# ---- 详情编辑器限制与护栏（2026-10-26 线上实测，口径=Quill 编辑器字数） ----
DETAIL_BUDGET = 404        # 实测可完整保存的上限（平台≈405）；超了会被**静默截断吞图**
DETAIL_IMGS = 10           # 详情图片上限（超图数平台报错拒收）
PC_DETAIL_BUDGET = 1000    # PC 详情（sync_item_info.info）编辑器标 x/1000


def editor_len(html):
    """Quill 编辑器字数口径：纯文本字符 + 块级(<p>/<br>) + 每图 1"""
    text = re.sub(r"<[^>]+>", "", html)
    blocks = len(re.findall(r"<p[ >]", html)) + html.count("<br")
    return len(text) + blocks + html.count("<img")


def sanitize_detail_html(html):
    """已知报错标签自动矫正：<b> → <strong>（平台报「非法字符: bad tag: b」）；
    其余标签（em/u 等，线上详情可见）不动，避免误伤既有内容。"""
    return re.sub(r"<(/?)b(?=[\s>/])", r"<\1strong", html, flags=re.I)


def validate_detail_html(html, budget=DETAIL_BUDGET, imgs_limit=DETAIL_IMGS):
    """发布护栏：超图数报错（平台拒收）、超字数报错（平台会静默截断吞图）。
    返回 (图数, 字数)。"""
    n_img = html.count("<img")
    ln = editor_len(html)
    if n_img > imgs_limit:
        raise DetailValidationError(
            "详情 %d 张图，超上限 %d（平台拒收）" % (n_img, imgs_limit))
    if ln > budget:
        raise DetailValidationError(
            "详情约 %d 字（Quill 口径）超上限 %d，超了会被静默截断吞图——"
            "请压缩正文或减少图片" % (ln, budget))
    return n_img, ln


def _no_login(j):
    return isinstance(j, dict) and (j.get("status") == "no_login"
                                    or "未登录" in str(j.get("msg") or ""))


class Api(object):
    """传输层：停靠在平台域的专用页面内 fetch（浏览器原生管理轮换cookie，最稳）；
    文件直传优先同通道，签名头不可读时回退 ctx.request。"""

    def __init__(self, log=lambda m: None):
        self.log = log
        self._ctx = None
        self._page = None   # 停靠页（停留在 https://mcdev.webapp.163.com/）

    def set_context(self, ctx, page=None):
        self._ctx = ctx
        if page is not None:
            self._page = page

    def ready(self):
        return self._ctx is not None

    # ---- 基础 ----
    _FETCH_JS = """async ([method, url, body]) => {
        const opt = {method: method, credentials: 'include',
                     headers: {'Accept': 'application/json, text/plain, */*'}};
        if (body !== null) {
            opt.headers['Content-Type'] = 'application/json';
            opt.body = body;
        }
        const r = await fetch(url, opt);
        const text = await r.text();
        return {status: r.status, text: text};
    }"""

    def _req(self, method, path, params=None, data=None, multipart=None, timeout=60000):
        if not self.ready():
            raise ApiError("API未就绪（浏览器未启动）")
        url = BASE + path.lstrip("/")
        if params:
            import urllib.parse as _up
            qs = _up.urlencode(params)
            url = url + ("&" if "?" in url else "?") + qs
        headers = {"Accept": "application/json, text/plain, */*"}
        if data is not None:
            headers["Content-Type"] = "application/json"  # 缺失时服务端解析body为空
        if self._page is not None:
            r = self._page.evaluate(
                "async ([method, url, body, headers]) => {"
                "const opt = {method: method, credentials: 'include', headers: headers};"
                "if (body !== null) opt.body = body;"
                "const r = await fetch(url, opt);"
                "return {status: r.status, text: await r.text()};}",
                [method, url, data, headers])
            status, body = r["status"], r["text"]
        else:
            rr = self._ctx.request.fetch(
                url, method=method, data=data, headers=headers,
                fail_on_status_code=False, timeout=timeout)
            status, body = rr.status, rr.text()
        try:
            j = json.loads(body)
        except ValueError:
            raise ApiError("HTTP %s: %s" % (status, body[:200]))
        if status != 200:
            raise ApiError("HTTP %s: %s" % (status, body[:200]))
        if _no_login(j):
            raise ApiError("API会话未登录")
        st = j.get("status")
        if st not in (None, "ok", 200, 0):
            errs = j.get("errors")
            detail = (" " + json.dumps(errs, ensure_ascii=False)) if errs else ""
            raise ApiError("接口错误 status=%s msg=%s%s"
                           % (st, j.get("msg") or j.get("message"), detail))
        code = j.get("code")
        if code not in (200, 0, None):
            raise ApiError("code=%s msg=%s" % (code, j.get("msg") or j.get("message")))
        data = j.get("data", j)
        return {} if data is None else data

    def get(self, path, **params):
        return self._req("GET", path, params=params or None)

    def post(self, path, body):
        return self._req("POST", path, data=json.dumps(body))

    def put(self, path, body=None):
        return self._req("PUT", path, data=json.dumps(body or {}))

    def _retry_write(self, fn, attempts=3):
        """写操作自动重试：网络抖动 / HTTP 5xx / 429（间隔 1s → 2.5s）。
        业务性拒绝（接口错误 status=…）不重试，避免重复提交。"""
        delay = 1.0
        for i in range(attempts):
            try:
                return fn()
            except ApiError as e:
                if not (str(e).startswith("HTTP 5") or str(e).startswith("HTTP 429")) \
                        or i == attempts - 1:
                    raise
            except Exception:
                if i == attempts - 1:
                    raise
            time.sleep(delay)
            delay *= 2.5

    # ---- 读 ----
    def user_info(self):
        d = self.get("users/me")
        return {"nickname": d.get("nickname"), "avatar": d.get("head_img"),
                "level": d.get("level"), "raw": d}

    def list_items(self):
        d = self.get("items/categories/pe/", start=0, span=100)
        items = []
        if isinstance(d, dict):
            for v in d.values():
                if isinstance(v, list) and v and isinstance(v[0], dict) \
                        and ("item_name" in v[0] or "item_id" in v[0]):
                    items = v
                    break
        rows = []
        for it in items:
            rows.append({
                "name": it.get("item_name") or "",
                "rid": str(it.get("item_id") or ""),
                "category": it.get("category") or "add_ons",
                "publish": str(it.get("online_time") or ""),
                "submit_at": str(it.get("commit_time") or it.get("check_time") or ""),
                "status": (it.get("mc_status_desc") or it.get("status_name")
                           or ("已上架" if it.get("online_status") in (1, "1", True) else "")),
                "raw": it,
            })
        return rows

    def detail(self, item_id):
        return self.get("items/categories/pe/%s" % item_id)

    # ---- 上传 ----
    def file_token(self, file_type):
        d = self.get("filepicker/file_token", file_type=file_type, secure="false")
        return d.get("token")

    def upload(self, file_type, file_path, mime="application/octet-stream"):
        """ctx.request 直传（共享浏览器cookie），返回 FileInfoDTO {body,file_type,sign}。"""
        token = self.file_token(file_type)
        if not token:
            raise ApiError("获取上传token失败")
        upload_url = self._upload_url_from_token(token)
        data = Path(file_path).read_bytes()
        import base64 as _b64
        sign = None
        body = ""
        status = 0
        if self._page is not None:
            js = """async ([url, token, name, mime, b64]) => {
                const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
                const fd = new FormData();
                fd.append('Authorization', token);
                fd.append('fpfile', new Blob([bytes], {type: mime}), name);
                const r = await fetch(url, {method: 'POST', body: fd});
                return {status: r.status, text: await r.text(),
                        sign: r.headers.get('x-ntes-signature')};
            }"""
            r = self._page.evaluate(js, [upload_url, token, Path(file_path).name,
                                         mime, _b64.b64encode(data).decode()])
            status, body, sign = r["status"], r["text"], r.get("sign")
        if status != 200 or not sign:
            # 回退：ctx.request 直传（部分响应头跨域不可读时）
            rr = self._ctx.request.post(
                upload_url,
                multipart={
                    "Authorization": token,
                    "fpfile": {"name": Path(file_path).name,
                               "mimeType": mime, "buffer": data}},
                fail_on_status_code=False, timeout=600000)
            body = rr.text()
            status = rr.status
            sign = (rr.headers or {}).get("x-ntes-signature")
        if status != 200:
            raise ApiError("上传HTTP %s: %s" % (status, body[:200]))
        if not sign:
            raise ApiError("上传响应缺签名头: %s" % body[:200])
        m = re.search(r"<textarea>(.*?)</textarea>", body, re.S)
        if m:
            fb = m.group(1).strip()
        else:
            try:
                j = json.loads(body)
                fb = json.dumps(j, ensure_ascii=False) if isinstance(j, dict) else body.strip()
            except ValueError:
                raise ApiError("上传响应无法解析: %s" % body[:200])
        return {"body": fb, "file_type": file_type, "sign": sign}

    @staticmethod
    def _upload_url_from_token(token):
        try:
            b64 = token.split(":", 1)[1]
            policy = json.loads(base64.b64decode(b64 + "==="))
            url = policy.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url
        except Exception:
            pass
        return UPLOAD_DEFAULT

    # ---- 写（UI显式触发） ----
    def update_item(self, item_id, body):
        return self._retry_write(lambda: self.post(
            "items/categories/pe/%s/update" % item_id, body))

    def apply_review(self, item_id, text=""):
        return self._retry_write(lambda: self.put(
            "items/categories/pe/%s/apply_review" % item_id,
            {"apply_review_text": text, "conflict_notify": 0,
             "is_check_apply": False}))


# ============ detail → update body（对齐 McDevManager toWorkUpdateDTO 矫正） ============
def _to_list(v):
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return v
    try:
        j = json.loads(v)
        if isinstance(j, list):
            return j
    except Exception:
        pass
    return [v]


def _to_obj(v):
    if isinstance(v, dict):
        return v
    try:
        j = json.loads(v or "{}")
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


def build_update_body(detail, changes=None):
    """detail: GET detail 的 data dict；changes 可含 item_name/update_summary/
    current_change_log/activity_desc/pe_game_introduction/info/new_res(FileInfoDTO)/
    new_res_name/add_version"""
    import time as _t
    changes = changes or {}
    b = dict(detail)

    def src(*names, default=None):
        for n in names:
            if n in detail and detail[n] not in (None, ""):
                return detail[n]
        return default

    b["is_check_apply"] = False
    b["pre_review_video"] = src("pre_review_video") or "{}"
    b["mc_version"] = _to_list(src("mc_version"))
    b["multi_tags"] = src("multi_tags") or "0"
    b["claim_item_enabled"] = bool(src("claim_item_enabled", default=0))
    b["exchange_currency_type"] = src("exchange_currency_type") or "ordinary"
    b["decompose_currency_type"] = src("decompose_currency_type") or "ordinary"
    b["running_status"] = src("running_status") or "normal"
    b["collection_id"] = src("collection_id") or "0"
    b["corp_proof_image"] = src("corp_proof_image") or None
    b["relate_item_id"] = int(src("relate_item_id", default=0) or 0)
    b["whitelist"] = _to_list(src("whitelist"))
    b["dyeing_relation"] = _to_obj(src("dyeing_relation"))
    now = int(_t.time())
    if detail.get("pe_is_add_play_plan") and (detail.get("play_plan_expire_time") or 0) > 0 \
            and detail["play_plan_expire_time"] < now:
        b["play_plan_expire_time"] = None
        b["play_plan_expire_month"] = 0
    else:
        # 未过期（含永久=-1）：原值透传；month 缺省补 0（发 null 报"有效期不能为空"）
        b["play_plan_expire_month"] = detail.get("play_plan_expire_month")
        if b["play_plan_expire_month"] is None:
            b["play_plan_expire_month"] = 0
    if not detail.get("sync_pc_flag"):
        b.pop("sync_item_info", None)
    else:
        b["sync_item_info"] = _to_obj(src("sync_item_info"))
    b["dyeing"] = src("dyeing") or ""
    b["activity_desc"] = src("activity_desc") or ""
    b["pe_game_introduction"] = src("pe_game_introduction") or ""

    # —— 边角字段矫正（实测 update 校验要求，端点同 McDevManager DTO）——
    # corp_proof_image：非原创/无证明时平台要求不发该键（空串=URL格式错误）
    if not b.get("corp_proof_image"):
        b.pop("corp_proof_image", None)
    # dlc_info：null 子字段 → 空容器
    dlc = b.get("dlc_info")
    dlc = _to_obj(dlc)
    if dlc.get("master") is None:
        dlc["master"] = {}
    if dlc.get("slave_list") is None:
        dlc["slave_list"] = []
    b["dlc_info"] = dlc
    # 副作用类型：null → 0（平台校验非空）
    if b.get("pri_effect_type") is None:
        b["pri_effect_type"] = 0
    if b.get("sub_effect_type") is None:
        b["sub_effect_type"] = 0
    # subject_id：空串属"数据格式错误" → JsonNull
    if b.get("subject_id") in ("", None):
        b["subject_id"] = None
    # openbeta/commercial：null 透传即可，"" → None
    for tk in ("openbeta_time", "commercial_time"):
        if b.get(tk) == "":
            b[tk] = None

    for k in ("item_name", "update_summary", "current_change_log",
              "activity_desc", "pe_game_introduction", "info"):
        if changes.get(k) is not None:
            b[k] = changes[k]

    res = detail.get("res")
    res = res if isinstance(res, list) else _to_list(res)
    new_res = changes.get("new_res")
    if new_res:
        entry = {
            "res_url": new_res,
            "res_name": changes.get("new_res_name") or "package.zip",
            "add_version": 1 if changes.get("add_version", True) else 0,
            "mc_version": _to_list(src("mc_version")),
        }
        if res:
            replaced = False
            for i, r in enumerate(res):
                rn = (r or {}).get("res_name") or ""
                if rn.endswith(".zip") or (r or {}).get("file_type") == "zip_package" or i == 0:
                    res[i] = entry
                    replaced = True
                    break
            if not replaced:
                res[0] = entry
        else:
            res = [entry]
        b["res"] = res
    else:
        b["res"] = res
    chan = detail.get("channel")
    b["channel"] = chan if isinstance(chan, list) else _to_list(chan)
    return b


# ============ 本地打包（移植 pack.ps1 逻辑，Python 版带进度） ============
def pack_project(project_dir, progress=None):
    """复刻 pack.ps1：扫描 *_behavior_pack/_resource_pack → 合并 zip。
    自动：删旧时间戳zip / manifest uuid 每次重生成 / 版本=今天日期[yy,m,d]。
    progress(frac, msg) 回调 0~1。返回 zip 路径。"""
    import uuid as _uuid
    import zipfile
    from datetime import date as _date
    project = Path(project_dir)
    packs = [p for p in project.iterdir()
             if p.is_dir() and (p.name.endswith("_behavior_pack")
                                or p.name.endswith("_resource_pack"))]
    if not packs:
        raise RuntimeError("未找到 *_behavior_pack/_resource_pack 目录")
    prefix = packs[0].name.rsplit("_", 2)[0] if "_behavior" in packs[0].name         else packs[0].name[:-len("_resource_pack")]
    today = _date.today()
    stamp = today.strftime("%Y-%m-%d_%H-%M-%S")
    out = project / ("%s_%s.zip" % (prefix, stamp))
    # 删旧时间戳zip（pack.ps1 默认行为）
    for old in project.glob("*_20??-??-??_??-??-??.zip"):
        try:
            old.unlink()
        except Exception:
            pass
    # uuid 全部重生成 + 版本=今天（模组发版惯例：身份隔离防碰撞）
    ver = [today.year % 100, today.month, today.day]
    for p in packs:
        mf = p / "manifest.json"
        if not mf.exists():
            continue
        m = json.loads(mf.read_text(encoding="utf-8-sig"))
        m["header"]["uuid"] = str(_uuid.uuid4())
        m["header"]["version"] = ver
        for mod in m.get("modules", []):
            mod["uuid"] = str(_uuid.uuid4())
            mod["version"] = ver
        mf.write_text(json.dumps(m, ensure_ascii=False, indent=4),
                      encoding="utf-8")
        if progress:
            progress(0.05, "%s manifest已更新" % p.name)

    total = 0
    file_list = []
    for p in packs:
        for root, dirs, files in os.walk(str(p)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f == ".DS_Store" or f.endswith(".pyc"):
                    continue
                file_list.append((Path(root) / f, p.name))
    n = len(file_list)
    if progress:
        progress(0.08, "共 %d 个文件" % n)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        done = 0
        for full, packname in file_list:
            rel = str(full.relative_to(project / packname)).replace(os.sep, "/")
            z.write(str(full), "%s/%s" % (packname, rel))
            done += 1
            if progress and (done % 40 == 0 or done == n):
                progress(0.08 + 0.9 * done / max(1, n),
                         "%s %d/%d" % (packname, done, n))
    if progress:
        progress(1.0, "完成 %s" % out.name)
    return out
