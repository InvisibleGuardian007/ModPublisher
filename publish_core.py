# -*- coding: utf-8 -*-
"""网易模组发布器 - 核心引擎：配置、模组数据、打包、平台读写自动化"""
import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

CONFIG_FILE = APP_DIR / "发布配置.json"
PROFILE_DIR = APP_DIR / "profile"
EDITOR_URL_RE = re.compile(r"#/pe/edit/\d+")

DEFAULT_CONFIG = {
    "browser_channel": "msedge",
    "list_url": "https://mcdev.webapp.163.com/#/work/list/pe_component",
    "max_note_len": 200,
    "mods": [
        {
            "id": "趣味附魔",
            "project_dir": "D:/MCModDve/MoreEnchantments",
            "resource_keyword": "趣味附魔",
            "name_template": "趣味附魔 - 共{n}个附魔",
            "count_glob": "InterestEnchant_behavior_pack/netease_enchants/*.json",
            "zip_glob": "InterestEnchant_*.zip",
            "pack_args": ["-KeepOld"],
            "changelog": "更新日志.md",
        },
        {
            "id": "僵尸启示录",
            "project_dir": "D:/MCModDve/ZombieApocalypse",
            "resource_keyword": "僵尸启示录",
            "name_template": "僵尸启示录：起源 - 共计{n}只新僵尸",
            "count_glob": "ZombieApocalypse_behavior_pack/entities/*.json",
            "zip_glob": "ZombieApocalypse_*.zip",
            "pack_args": ["-KeepOld"],
            "changelog": "更新日志.md",
        },
        {
            "id": "头颅不仅仅是装饰品",
            "project_dir": "D:/MCModDve/MorePracticalSkull",
            "resource_keyword": "头颅不仅仅是装饰品",
            "name_template": None,
            "count_glob": None,
            "zip_glob": "*.zip",
            "pack_args": ["-KeepOld"],
            "changelog": None,
        },
    ],
}


# ============ 配置与模组数据 ============
def load_config():
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    for k, v in DEFAULT_CONFIG.items():
        if k != "mods":
            cfg.setdefault(k, v)
    cfg.setdefault("mods", [])
    return cfg


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def project_dir(mod):
    p = Path(mod["project_dir"])
    if not p.is_absolute():
        p = (APP_DIR / p).resolve()
    return p


def mod_info(mod):
    """本地可得的模组信息（不碰浏览器）"""
    pdir = project_dir(mod)
    info = {"id": mod["id"], "dir_ok": pdir.is_dir(), "version": None,
            "count": None, "name_suggest": None, "note_suggest": None,
            "zip_latest": None}
    if not info["dir_ok"]:
        return info
    for mf in sorted(pdir.glob("*_behavior_pack/manifest.json")):
        try:
            v = json.loads(mf.read_text(encoding="utf-8-sig"))["header"]["version"]
            info["version"] = ".".join(str(x) for x in v)
            break
        except Exception:
            continue
    g = mod.get("count_glob")
    if g:
        info["count"] = len(glob.glob(str(pdir / g)))
    tpl = mod.get("name_template")
    if tpl:
        info["name_suggest"] = tpl.replace("{n}", str(info["count"])) if info["count"] is not None else tpl
    zips = sorted(pdir.glob(mod.get("zip_glob") or "*.zip"), key=os.path.getmtime)
    if zips:
        info["zip_latest"] = zips[-1].name
    info["note_suggest"] = build_note(mod, pdir)
    return info


def build_note(mod, pdir, max_len=200):
    cf = mod.get("changelog")
    if not cf:
        return None
    f = pdir / cf
    if not f.exists():
        return None
    m = re.search(r"## 系统调整\n(.*?)\n##", f.read_text(encoding="utf-8-sig"), re.S)
    if not m:
        return None
    items = [l.strip("- ").strip() for l in m.group(1).strip().splitlines() if l.startswith("- ")]
    if not items:
        return None
    ver = None
    for mf in sorted(pdir.glob("*_behavior_pack/manifest.json")):
        try:
            v = json.loads(mf.read_text(encoding="utf-8-sig"))["header"]["version"]
            ver = ".".join(str(x) for x in v)
            break
        except Exception:
            continue
    note = ("%s更新：" % ver if ver else "") + "；".join(items)
    return note[: max_len - 1] + "…" if len(note) > max_len else note


def pack(mod):
    """打包（有 pack.ps1 才打），返回 zip 路径；失败抛异常。"""
    pdir = project_dir(mod)
    if not pdir.is_dir():
        raise RuntimeError("项目目录不存在: %s" % pdir)
    zg = mod.get("zip_glob") or "*.zip"
    if (pdir / "pack.ps1").exists():
        before = set(pdir.glob(zg))
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File",
               str(pdir / "pack.ps1")] + (mod.get("pack_args") or ["-KeepOld"])
        r = subprocess.run(cmd, cwd=str(pdir), capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("打包失败:\n%s%s" % (r.stdout or "", r.stderr or ""))
        time.sleep(1)
        new = set(pdir.glob(zg)) - before
        cands = new if new else set(pdir.glob(zg))
    else:
        cands = set(pdir.glob(zg))
    if not cands:
        raise RuntimeError("没有匹配 %s 的 zip，且无 pack.ps1" % zg)
    return sorted(cands, key=os.path.getmtime)[-1]


# ============ 浏览器引擎（常驻工作线程内运行） ============
class BrowserEngine(object):
    """所有方法只允许在创建它的同一线程调用（Playwright sync 限制）。"""

    def __init__(self, cfg, emit):
        self.cfg = cfg
        self.emit = emit          # emit(kind, payload) 回调（线程安全转发给UI）
        self._pw = None
        self._ctx = None
        self._browser = None
        self._attached = False    # True=CDP 附加（窗口复用，非 Playwright 托管）
        self._popped = False      # True=本脚本拉起的 Edge 进程
        self.page = None
        self._editor_mod = None   # 当前停在编辑页的模组id

    def log(self, msg):
        self.emit("log", msg)

    # ---- 生命周期 ----
    CDP = "http://127.0.0.1:9222"

    @staticmethod
    def _find_edge():
        for base in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("LocalAppData", "")):
            p = Path(base) / "Microsoft/Edge/Application/msedge.exe"
            if p.exists():
                return str(p)
        return None

    @staticmethod
    def _kill_stale():
        """杀掉占着 profile 锁但没开调试端口的残留 Edge（无法附加，只能清掉）。"""
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"name='msedge.exe'\" | "
                 "Where-Object { $_.CommandLine -like '*%s*profile*' -and "
                 "$_.CommandLine -notlike '*remote-debugging-port*' } | "
                 "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
                 "-ErrorAction SilentlyContinue }" % APP_DIR.name],
                capture_output=True, timeout=20)
        except Exception:
            pass

    def _cdp_alive(self, wait):
        import urllib.request as _u
        deadline = time.time() + wait
        while time.time() < deadline:
            try:
                with _u.urlopen(self.CDP + "/json/version", timeout=1) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(0.4)
        return False

    def _connect(self, timeout=8000):
        """CDP 附加并选定默认上下文（=浏览器自身 profile，登录态原样可用）。"""
        b = self._pw.chromium.connect_over_cdp(self.CDP, timeout=timeout)
        ctx = b.contexts[0] if b.contexts else None
        if ctx is None:
            b.close()
            raise RuntimeError("Edge 无可用上下文")
        self._browser = b
        self._attached = True
        self._ctx = ctx
        self.page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            b.on("disconnected", lambda *_: self.emit("browser_gone", None))
        except Exception:
            pass
        self.emit("browser_up", None)

    def _ensure_browser(self):
        if self._ctx:
            return
        self._pw = sync_playwright().start()
        # 1) 附加优先：窗口还开着（哪怕上次脚本已退出）就原样接管，绝不新开窗口
        try:
            self._connect(timeout=3000)
            self.log("已附加到现有发布器窗口（窗口复用）")
            return
        except Exception:
            pass
        # 2) 拉起独立 Edge 进程（不经 Playwright 托管：脚本退出窗口仍在，
        #    下次启动附加复用——同一窗口反复使用，只有关窗后才会新开）
        self._kill_stale()
        exe = self._find_edge()
        if not exe:
            raise RuntimeError("未找到 msedge.exe，请安装 Microsoft Edge")
        args = [exe,
                "--remote-debugging-port=9222",
                "--user-data-dir=%s" % PROFILE_DIR,
                "--window-position=20,20", "--window-size=1360,1000",
                "--hide-crash-restore-bubble", "--no-first-run",
                "--no-default-browser-check"]
        if bool(self.cfg.get("headless_browser", False)):
            args.append("--headless=new")
        args.append("about:blank")
        self._popped = True
        subprocess.Popen(args)
        if not self._cdp_alive(30):
            raise RuntimeError("Edge 启动超时（9222 未就绪）")
        self._connect()
        self.log("浏览器已启动（窗口常驻，脚本重启自动复用）")

    def close(self, kill=None):
        """断开连接。kill=None 时自动判断：仅清理本脚本拉起的无头实例；
        有头窗口一律保留（用户手动关窗，下次启动复用同一窗口）。"""
        if kill is None:
            kill = bool(self._popped) and bool(self.cfg.get("headless_browser", False))
        if kill:
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_Process -Filter \"name='msedge.exe'\" | "
                     "Where-Object { $_.CommandLine -like '*%s*profile*' } | "
                     "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
                     "-ErrorAction SilentlyContinue }" % APP_DIR.name],
                    capture_output=True, timeout=20)
            except Exception:
                pass
        try:
            if self._browser:
                self._browser.close()   # CDP 连接模式：仅断开，不杀浏览器
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = None
        self._browser = None
        self._pw = None
        self.page = None
        self._editor_mod = None

    # ---- 登录 ----
    def logged_in(self):
        return "login" not in (self.page.url or "")

    def read_profile(self):
        """抓登录者昵称和头像（已对真实页面验证：'注销'可能非叶子节点，
        用"含注销文本的最小元素"做锚，向上找容器取其前最近短文本叶子+img）。"""
        try:
            self._ensure_browser()
            return self.page.evaluate(
                """() => {
                let name = null, avatar = null;
                const cand = [...document.querySelectorAll('body *')]
                    .filter(e => (e.textContent || '').includes('注销'));
                const smallest = cand.sort((a, b) =>
                    a.textContent.length - b.textContent.length)[0] || null;
                if (smallest) {
                    let c = smallest;
                    for (let lvl = 0; lvl < 6 && !name; lvl++) {
                        c = c.parentElement;
                        if (!c) break;
                        const leaves = [...c.querySelectorAll('*')].filter(e => {
                            if (e.children.length) return false;
                            const t = (e.textContent || '').trim();
                            return t && t.length >= 2 && t.length <= 16 &&
                                !['注销', '系统消息', '公告', '下载「手机版测试工具」'].includes(t);
                        });
                        const before = leaves.filter(e => {
                            try {
                                return e.compareDocumentPosition(smallest) & 4;
                            } catch (_) { return false; }
                        });
                        if (before.length) name = before[before.length - 1].textContent.trim();
                        if (!avatar) {
                            const img = c.querySelector('img');
                            if (img && img.src && img.src.startsWith('http'))
                                avatar = img.src;
                        }
                    }
                }
                return {name, avatar};
            }""")
        except Exception:
            return {"name": None, "avatar": None}

    def open_login(self, timeout_s=180):
        """打开登录页等待用户人工登录，轮询直到登录成功或超时。"""
        self._ensure_browser()
        self.page.goto(self.cfg["list_url"], wait_until="domcontentloaded")
        self.page.wait_for_timeout(2000)
        if self.logged_in():
            return True
        self.emit("status", "等待登录（请在弹出的浏览器里登录，建议勾选十天免登录）")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            self.page.wait_for_timeout(2000)
            try:
                if self.logged_in():
                    self.emit("status", "已登录")
                    return True
            except Exception:
                pass
        return False

    # ---- 导航 ----
    def _goto_list(self):
        self._ensure_browser()
        cur = self.page.url or ""
        if "#/work/list" not in cur:  # 已在列表页就不重载（重载会引发登录态暂态）
            self.page.goto(self.cfg["list_url"], wait_until="domcontentloaded")
            self.page.wait_for_timeout(1200)
        # SPA 重载后可能短暂路过登录路由：等几秒，持续在登录页才算真的未登录
        for _ in range(4):
            if self.logged_in():
                break
            self.page.wait_for_timeout(1200)
        if not self.logged_in():
            raise RuntimeError("未登录：请先点「登录」")
        # 等数据表真正渲染出来（SPA 异步加载，慢网络下固定 sleep 不够）
        try:
            self.page.wait_for_selector("table tr td", timeout=15000)
        except Exception:
            pass
        self.page.wait_for_timeout(800)

    def read_list(self):
        """读取平台作品列表全部行：名称/资源ID/类别/发布时间/提审时间/状态。"""
        self._goto_list()
        js = """() => {
            const trs = [...document.querySelectorAll('table tr')];
            const out = [];
            for (const tr of trs) {
                const tds = tr.querySelectorAll('td');
                if (tds.length < 5) continue;
                const lines = (tds[0].innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
                out.push({
                    name: lines[0] || '',
                    rid: lines[1] || '',
                    category: (tds[1].innerText || '').trim(),
                    publish: (tds[2].innerText || '').trim(),
                    submit_at: (tds[3].innerText || '').trim(),
                    status: (tds[4].innerText || '').trim(),
                });
            }
            return out.filter(r => r.name);
        }"""
        rows = []
        for _ in range(3):  # 表格慢加载时重试
            rows = self.page.evaluate(js)
            if rows:
                break
            self.page.wait_for_timeout(2500)
        self.log("平台列表已刷新：%d 个作品" % len(rows))
        return rows

    def open_editor(self, pattern, key=None):
        """进入某个作品的编辑页（已在则复用）。pattern=正则源文本（调用方负责转义）。"""
        key = key or pattern
        if self._editor_mod == key and EDITOR_URL_RE.search(self.page.url or ""):
            return
        self._goto_list()
        row = self.page.get_by_role("row", name=re.compile(pattern))
        row.wait_for(state="visible", timeout=15000)
        btn = row.get_by_role("button", name="更新")
        if btn.count() != 1:
            btn = row.get_by_role("button", name="编辑")
        if btn.count() != 1:
            raise RuntimeError("「%s」行里找不到 更新/编辑 按钮，请到平台人工检查状态" % match_text)
        btn.first.click()
        self.page.wait_for_url(EDITOR_URL_RE, timeout=20000)
        self.page.wait_for_timeout(2500)
        self._editor_mod = key
        self.log("已进入编辑页: %s" % self.page.url.split("#")[-1])

    # ---- 读当前值（优先加载，不覆盖） ----
    def read_current(self, row_name):
        self.open_editor(re.escape(row_name), key=row_name)
        data = self.page.evaluate(
            """() => {
            const out = {};
            const nameInp = document.querySelector('input[placeholder="请输入资源名称"]');
            out.name = nameInp ? nameInp.value : null;
            const leaf = (txt) => [...document.querySelectorAll('*')]
                .find(e => !e.children.length && e.textContent.trim() === txt);
            const siblingVal = (labelTxt, re) => {
                const lf = leaf(labelTxt);
                if (!lf) return null;
                const seg = (lf.parentElement && lf.parentElement.textContent) || '';
                const m = seg.match(re);
                return m ? m[0] : null;
            };
            out.res_version = siblingVal('资源版本', /\\d+\\.\\d+(?:\\.\\d+)?/);
            out.mod_code = siblingVal('模组码', /\\d{5,}/);
            // 标签（Element UI tag）
            out.tags = [...document.querySelectorAll('.el-tag')]
                .map(t => (t.textContent || '').trim()).filter(Boolean).slice(0, 12);
            // 定价
            const priceInp = [...document.querySelectorAll('input')].find(
                i => (i.value || '').includes('档'));
            out.price = priceInp ? priceInp.value : null;
            // 各文本域
            const tas = [...document.querySelectorAll('textarea.el-textarea__inner')];
            out.activity = (tas.find(t => (t.placeholder || '').includes('用于填写参与官方活动')) || {}).value || null;
            out.pc_intro = (tas.find(t => (t.placeholder || '') === '请输入简介') || {}).value || null;
            out.note = (tas.find(t => t.value.includes('请到详细界面查看')) || {}).value || null;
            // PE详情富文本：纯文本 + 原始HTML
            const qe = document.querySelector('.ql-editor');
            out.detail_plain = qe ? (qe.innerText || '').slice(0, 1200) : null;
            out.detail_html = qe ? qe.innerHTML : null;
            // 已上传 zip
            const zips = [...document.querySelectorAll('input[type=file][name=fpfile]')];
            const zipNames = [];
            for (const inp of zips) {
                let e = inp;
                for (let i = 0; i < 8 && e; i++) {
                    const m = (e.textContent || '').match(/[A-Za-z_][\\w-]*\\.zip\\b/);
                    if (m) { zipNames.push(m[0]); break; }
                    e = e.parentElement;
                }
            }
            out.zip = zipNames.length ? zipNames[0] : null;
            return out;
        }"""
        )
        self.log("已读取表单: 名称=%r 资源版本=%s 已传包=%s 标签=%s" % (
            data.get("name"), data.get("res_version"), data.get("zip"),
            "、".join(data.get("tags") or [])[:40]))
        return data

    # ---- 写入（只写勾选的项） ----
    def _mark_zip_input(self):
        return self.page.evaluate(
            """() => {
            const inputs = [...document.querySelectorAll('input[type=file][name=fpfile]')];
            const zipHits = [];
            for (const inp of inputs) {
                let el = inp, found = false;
                for (let i = 0; i < 6 && el; i++) {
                    if (el.textContent && el.textContent.includes('限制格式：zip')) { found = true; break; }
                    el = el.parentElement;
                }
                if (found) zipHits.push(inp);
            }
            let target = null;
            for (const inp of zipHits) {
                let e = inp;
                for (let i = 0; i < 8 && e; i++) {
                    if (/[A-Za-z_][\\w-]*\\.zip\\b/.test(e.textContent || '')) { target = inp; break; }
                    e = e.parentElement;
                }
                if (target) break;
            }
            if (!target && zipHits.length) target = zipHits[0];
            if (!target) return false;
            target.setAttribute('data-publish-zip', '1');
            return true;
        }"""
        )

    def apply_and_save(self, row_name, actions):
        """actions: {zip_path, boost, name, note} —— None 表示该项不动。
        返回必填项扫描结果。"""
        self.open_editor(re.escape(row_name), key=row_name)
        done = []
        if actions.get("zip_path"):
            if not self._mark_zip_input():
                raise RuntimeError("未定位到 zip 上传控件（平台改版？），已停止且未保存")
            zp = actions["zip_path"]
            self.log("上传: %s" % os.path.basename(zp))
            self.page.locator("input[data-publish-zip='1']").set_input_files(str(zp))
            self.page.get_by_text(os.path.basename(zp)).first.wait_for(
                state="visible", timeout=180000)
            self.page.wait_for_timeout(1500)
            done.append("上传新包")
        if actions.get("boost"):
            boost = self.page.locator("div.el-form-item", has=self.page.get_by_text("提升版本", exact=True))
            if boost.count() != 1:
                raise RuntimeError("「提升版本」定位异常，已停止且未保存")
            boost.get_by_role("radio", name="是").check()
            self.page.wait_for_timeout(500)
            done.append("提升版本")
        if actions.get("name"):
            inp = self.page.get_by_role("textbox", name="请输入资源名称")
            old = inp.input_value()
            inp.fill(actions["name"])
            self.page.wait_for_timeout(300)
            done.append("名称 %r→%r" % (old, actions["name"]))
        if actions.get("activity"):
            box = self.page.get_by_placeholder(re.compile("用于填写参与官方活动"))
            box.fill(actions["activity"])
            self.page.wait_for_timeout(200)
            done.append("活动参与说明")
        if actions.get("pc_intro"):
            box = self.page.get_by_placeholder(re.compile("^请输入简介$"))
            box.fill(actions["pc_intro"])
            self.page.wait_for_timeout(200)
            done.append("PC模组简介")
        if actions.get("note"):
            note = actions["note"][: self.cfg.get("max_note_len", 200)]
            idx_marked = self.page.evaluate(
                """() => {
                const t = [...document.querySelectorAll('textarea.el-textarea__inner')]
                    .find(x => x.value.includes('请到详细界面查看'));
                if (!t) return false;
                t.setAttribute('data-publish-note', '1'); return true;
            }"""
            )
            if not idx_marked:
                raise RuntimeError("未定位到「PE更新纪要」输入框，已停止且未保存")
            self.page.locator("textarea[data-publish-note='1']").fill(note)
            self.page.wait_for_timeout(300)
            done.append("更新纪要(%d字)" % len(note))
        if actions.get("detail_html"):
            ok = self.page.evaluate(
                """(html) => {
                const ed = document.querySelector('.ql-editor');
                if (!ed) return false;
                ed.innerHTML = html;
                ed.dispatchEvent(new Event('input', {bubbles: true}));
                return true;
            }""", actions["detail_html"])
            if not ok:
                raise RuntimeError("未找到详情编辑器，已停止且未保存")
            self.page.wait_for_timeout(500)
            done.append("详情图文(%d块HTML)" % len(actions["detail_html"]))
        self.log("本次写入: %s" % ("；".join(done) if done else "（无改动项）"))

        scan = self.page.evaluate(
            """() => {
            const items = [...document.querySelectorAll('.el-form-item.is-required')];
            return items.map(it => {
                const label = ((it.querySelector('.el-form-item__label, label') || {}).textContent || '').trim();
                const anyText = [...it.querySelectorAll('input:not([type=radio]):not([type=file]):not([type=hidden])')]
                    .some(i => (i.value || '').trim());
                const anyRadio = !!it.querySelector('input[type=radio]:checked');
                const anyFile = !!it.querySelector('.el-upload-list li, .el-upload-list__item');
                return {label: label.slice(0, 24), state: (anyText || anyRadio || anyFile) ? '已填' : '未填'};
            }).filter(x => x.label);
        }"""
        )
        self.log("必填项扫描（%d项）: %s" % (
            len(scan), "全部已填" if all(s["state"] == "已填" for s in scan)
            else "未填→ " + "、".join(s["label"] for s in scan if s["state"] == "未填")))

        self.log("点击「保存」...")
        self.page.get_by_role("button", name="保存", exact=True).click()
        self.page.wait_for_timeout(3000)
        self.log("保存完成")
        return scan

    def submit(self):
        self.log("点击「提交审核」...")
        self.page.get_by_role("button", name="提交审核", exact=True).click()
        self.page.wait_for_timeout(2000)
        confirm = self.page.get_by_role("button", name=re.compile(r"^\s*确\s*定\s*$"))
        if confirm.count() > 0:
            confirm.first.click()
            self.log("已确认平台弹窗")
        self.page.wait_for_timeout(4000)
        self._editor_mod = None
        self.log("已提交审核，结果请到平台「上架与资源管理」查看")

    # ---- 详情图文（原生编辑支撑） ----
    def set_detail_html(self, row_name, html):
        """把详情编辑器内容整体替换为给定 HTML（Quill root + input 事件同步 v-model）。"""
        self.open_editor(re.escape(row_name), key=row_name)
        ok = self.page.evaluate(
            """(html) => {
            const ed = document.querySelector('.ql-editor');
            if (!ed) return false;
            ed.innerHTML = html;
            ed.dispatchEvent(new Event('input', {bubbles: true}));
            return true;
        }""", html)
        if not ok:
            raise RuntimeError("未找到详情富文本编辑器（平台改版？）")
        self.log("详情内容已写入（%d字符HTML）" % len(html))

    def upload_detail_image(self, row_name, file_path):
        """通过平台详情编辑器自带的文件控件上传图片，返回上传后的详情HTML。"""
        self.open_editor(re.escape(row_name), key=row_name)
        marked = self.page.evaluate(
            """() => {
            // 优先 PE详情信息 区块里的 .edit-quill 文件input
            const quills = [...document.querySelectorAll('.edit-quill')];
            for (const q of quills) {
                let seg = q;
                for (let i = 0; i < 8 && seg; i++) {
                    if ((seg.textContent || '').includes('PE详情信息')) {
                        const inp = q.querySelector('input[type=file]');
                        if (inp) { inp.setAttribute('data-detail-img', '1'); return true; }
                    }
                    seg = seg.parentElement;
                }
            }
            const any = document.querySelector('.edit-quill input[type=file]');
            if (any) { any.setAttribute('data-detail-img', '1'); return true; }
            return false;
        }"""
        )
        if not marked:
            raise RuntimeError("未找到详情图片上传控件（平台改版？）")
        self.log("上传详情图片: %s" % os.path.basename(file_path))
        before = self.page.evaluate(
            "() => { const e = document.querySelector('.ql-editor'); return e ? e.innerHTML : ''; }")
        self.page.locator("input[data-detail-img='1']").set_input_files(str(file_path))
        for _ in range(20):
            self.page.wait_for_timeout(1000)
            html = self.page.evaluate(
                "() => { const e = document.querySelector('.ql-editor'); return e ? e.innerHTML : ''; }")
            if html and html != before and "loading" not in html.lower():
                self.page.wait_for_timeout(1500)  # 等URL替换完成
                html = self.page.evaluate(
                    "() => { const e = document.querySelector('.ql-editor'); return e ? e.innerHTML : ''; }")
                return html
        raise RuntimeError("详情图片上传超时（20秒未见变化）")
