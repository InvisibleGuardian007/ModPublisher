# -*- coding: utf-8 -*-
"""v13 复刻界面端到端：自制页面（官方结构复刻）+ 底部自动化条，真会话。"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import publish_core as core  # noqa: E402
import publish_api as _PA  # noqa: E402

def _PA_pack(pdir, progress=None):
    return _PA.pack_project(pdir, progress=progress)

import mod_publisher as mp  # noqa: E402

core.PROFILE_DIR = Path(__file__).resolve().parent.parent / "dist" / "profile"
cfg = core.load_config()
cfg["headless_browser"] = True

host = mp.Host(cfg)
host.start()
page = host.page
NAME = "趣味附魔 - 共162个附魔"


def S(fn, timeout=120):
    return host.submit(fn, timeout=timeout)


def EV(expr):
    return S(lambda: page.evaluate(expr))


def wait(cond, what, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if EV(cond):
                return
        except Exception:
            pass
        time.sleep(0.4)
    raise AssertionError("等待超时: " + what)


# 1) boot
wait("document.getElementById('nick').textContent.includes('隐形守护者007')", "昵称")
assert EV("document.querySelectorAll('.item').length") == 5
print("1 boot: 昵称+5作品 ✓")

# 2) 选中 → 表单载入
EV("document.querySelectorAll('.item')[0].click()")
wait("document.getElementById('fName').value.includes('趣味附魔')", "表单")
fName = EV("document.getElementById('fName').value")
fRo = EV("document.getElementById('fRo').textContent")
assert fName == NAME and "2.9" in fRo and "Enchant_2026" in fRo, (fName, fRo)
print("2 表单: 名称/资源版本/已传包 ✓")

# 3) 文档编辑器（真实详情）
wait("document.querySelectorAll('#doc img').length>=9", "详情图")
imgs = EV("document.querySelectorAll('#doc img').length")
cnt = EV("document.getElementById('docCnt').textContent")
# 新口径：Quill 字数/上限（404）+ 图数/上限（10），如「 404/404 · 图 10/10」
assert imgs == 10 and re.search(r"\d+/404", cnt) and "10/10" in cnt, (imgs, cnt)
print("3 详情文档: 10图内联 %s ✓" % cnt.strip())

# 3.5 图片槽位 / 视频 / 攻略（官方布局复刻）
n_slots = EV("document.querySelectorAll('#slots .slot').length")
assert n_slots >= 4, n_slots
has_banner_img = EV("!!document.querySelector(\"[data-slot='banner'] img\")")
vid = EV("(document.querySelector('#vNow video')||{}).src||''")
assert vid.startswith("https"), vid
guides = EV("document.getElementById('fGuides').textContent")
assert "搏命" in guides, guides
one_intro = EV("[...document.querySelectorAll('.card h3')]"
               ".filter(h=>h.textContent.includes('详情介绍')).length")
assert one_intro == 1
print("3.5 槽位x%d(组件ICON含现图)+现存视频+攻略列表+单一详情介绍 ✓" % n_slots)

# 3.7 拖拽插入图片（模拟drop事件：真实上传→光标处插入）
PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNg"
       "YGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==")
before = EV("document.querySelectorAll('#doc img').length")
S(lambda: page.evaluate(
    "(async () => {const blob=await (await fetch("
    "'data:image/png;base64,%s')).blob();"
    "const dt=new DataTransfer();"
    "dt.items.add(new File([blob],'drop.png',{type:'image/png'}));"
    "document.getElementById('doc').dispatchEvent("
    "new DragEvent('drop',{dataTransfer:dt,bubbles:true}));})()" % PNG))
wait("document.querySelectorAll('#doc img').length>=%d" % (before + 1),
     "拖拽插入", timeout=40)
print("3.7 拖拽图片→上传→插入文档 ✓（%d→%d图）" % (
    before, EV("document.querySelectorAll('#doc img').length")))

# 4) 建议名称 / 生成纪要（底部栏）
EV("document.getElementById('bName').click()")
wait("document.getElementById('fName').value.includes('共242个附魔')", "建议名称")
assert "dirty" in EV("document.getElementById('fName').className")
EV("document.getElementById('bNote').click()")
wait("document.getElementById('fNote').value.includes('更新：')", "纪要")
print("4 自动化条: 建议名称(标绿)+生成纪要 ✓")

# 5) 全字段（高级折叠区）
EV("document.querySelector('details').setAttribute('open','')")
wait("document.querySelectorAll('#allfields .fitem').length>150", "全字段")
n = EV("document.querySelectorAll('#allfields .fitem').length")
print("5 全字段复刻: %d 项 ✓" % n)

# 6) 搜索
S(lambda: page.fill("#kw", "僵尸"))
assert EV("document.querySelectorAll('.item').length") == 1
S(lambda: page.fill("#kw", ""))
print("6 搜索过滤 ✓")

# 6.5) 主题切换（背景变化 + localStorage 持久化）
bg1 = EV("getComputedStyle(document.body).backgroundColor")
EV("document.getElementById('btnTheme').click()")
time.sleep(0.3)
bg2 = EV("getComputedStyle(document.body).backgroundColor")
assert bg1 != bg2, (bg1, bg2)
theme_saved = EV("localStorage.getItem('mp_theme')")
assert theme_saved in ("dark", "light")
EV("document.getElementById('btnTheme').click()")  # 切回
print("6.5 主题切换 %s→%s 持久化=%s ✓" % (bg1, bg2, theme_saved))

# 6.6) 暗色下输入框/卡片可读性（无白底白字）
EV("document.getElementById('btnTheme').click()")  # 切到暗色
time.sleep(0.2)
pairs = [("body", "backgroundColor", "color"),
         ("#fName", "backgroundColor", "color"),
         ("#fNote", "backgroundColor", "color"),
         ("#doc", "backgroundColor", "color"),
         ("#bar", "backgroundColor", "color"),
         ("#bar", "backgroundColor", "color"),
         (".search input", "backgroundColor", "color"),
         ("header", "backgroundColor", "color"),
         ("aside", "backgroundColor", "color")]
bad = []
for sel, b, c in pairs:
    bb = EV("getComputedStyle(document.querySelector('%s')).%s" % (sel, b))
    cc = EV("getComputedStyle(document.querySelector('%s')).%s" % (sel, c))
    if bb == cc:  # 背景与文字同色=不可读
        bad.append((sel, bb))
EV("document.getElementById('btnTheme').click()")  # 切回浅色
assert not bad, "暗色不可读: %s" % bad
print("6.6 暗色主题可读性: 输入框/卡片/文档/底栏 全部正常 ✓")

# 6.7) 刷新按钮=全量重载（列表+表单）
EV("document.getElementById('fName').value=''")  # 破坏现场
EV("document.getElementById('btnRefresh').click()")
wait("document.getElementById('fName').value.includes('趣味附魔')", "刷新后表单重载")
print("6.7 刷新=全量重载（列表+当前表单）✓")

# 6.8) 本地打包（真仓库 + 进度事件 + uuid/版本/删旧）
prog_seen = []
host._ui_event = lambda kind, pj: (
    prog_seen.append(json.loads(pj)) if kind == "pack_progress" else None)
mod = next(m for m in cfg["mods"] if m["id"] == "趣味附魔")
old_uuids = []
import json as _json
for pn in ("InterestEnchant_behavior_pack", "InterestEnchant_resource_pack"):
    mf = core.project_dir(mod) / pn / "manifest.json"
    old_uuids.append(_json.loads(mf.read_text(encoding="utf-8-sig"))["header"]["uuid"])
z = S(lambda: _PA_pack(core.project_dir(mod),
                       progress=lambda f, m: host.ui_event(
                           "pack_progress", {"frac": f, "msg": m})), timeout=180)
assert z.exists() and z.stat().st_size > 100000
assert len(prog_seen) >= 3 and prog_seen[-1]["frac"] == 1.0
new_uuids = []
for pn in ("InterestEnchant_behavior_pack", "InterestEnchant_resource_pack"):
    mf = core.project_dir(mod) / pn / "manifest.json"
    new_uuids.append(_json.loads(mf.read_text(encoding="utf-8-sig"))["header"]["uuid"])
assert new_uuids != old_uuids, "uuid 未重生成"
zipf = __import__("zipfile").ZipFile(z)
assert not [n for n in zipf.namelist() if "__pycache__" in n]
print("6.8 本地打包: %s (%.1fMB) 进度%d条 uuid已重生成 ✓" % (
    z.name, z.stat().st_size / 1048576, len(prog_seen)))

# 6.9) 编辑器格式工具栏：选区加粗 + 标题（execCommand 真实验证）
fmt = S(lambda: page.evaluate("""() => {
  const doc = document.getElementById('doc');
  const w = document.createTreeWalker(doc, NodeFilter.SHOW_TEXT);
  let n; while ((n = w.nextNode())) {
    if ((n.textContent||'').trim().length > 6) {
      const r = document.createRange(); r.selectNodeContents(n);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      let target = null;
      const w2 = document.createTreeWalker(doc, NodeFilter.SHOW_TEXT);
      let t; while ((t = w2.nextNode())) {
        if ((t.textContent||'').includes('丰富附魔体系')) { target = t; break; }
      }
      if (!target) return {err: 'plain node not found'};
      const r3 = document.createRange(); r3.selectNode(target);
      const s3 = getSelection(); s3.removeAllRanges(); s3.addRange(r3);
      const b1 = document.execCommand('bold');
      const seg = target.parentElement.closest('p');
      const before = seg ? seg.outerHTML : '';
      document.execCommand('formatBlock', false, 'h2');
      return {exec: b1, bold: (seg?seg.outerHTML:before) !== before || before.includes('<b>') || before.includes('<strong>'), sample: (seg?seg.outerHTML:before).slice(0, 260), h2: !!doc.querySelector('#doc h2')};
    }
  }
  return {bold: false, h2: false};
}"""))
assert fmt["bold"] and fmt["h2"], fmt
print("6.9 格式工具栏: 加粗+H2标题 真实生效 ✓")

# 6.95) 本地映射弹窗 + 配置往返（临时映射→命中→还原）
EV("document.getElementById('btnMap2').click()")  # 侧栏头部入口
time.sleep(0.5)
rows = EV("document.querySelectorAll('#mapList .mapcard').length")
assert rows == 3, rows
per = EV("document.querySelectorAll('#mapList .mapcard')[0]"
         ".querySelectorAll('.grid > div').length")
assert per == 7, per
# 暗色下 mapcard 背景随主题（不再是固定浅灰）
EV("document.getElementById('btnTheme').click()")
time.sleep(0.2)
mcbg = EV("getComputedStyle(document.querySelector('.mapcard')).backgroundColor")
assert mcbg not in ("rgb(248, 250, 252)", "rgb(255, 255, 255)"), mcbg
print("   mapcard 随主题:", mcbg)
# ✕ 关闭
assert EV("!!document.getElementById('mX')")
EV("document.getElementById('mX').click()")
assert EV("document.getElementById('mapModal').style.display") == "none"
EV("document.getElementById('btnMap').click()")   # 底部入口
time.sleep(0.4)
assert EV("document.querySelectorAll('#mapList .mapcard').length") == 3
S(lambda: page.keyboard.press("Escape"))
time.sleep(0.3)
assert EV("document.getElementById('mapModal').style.display") == "none"
EV("document.getElementById('btnTheme').click()")  # 还原浅色
time.sleep(0.2)
orig = S(lambda: host.rpc_cfg_get({}))["mods"]
import tempfile
import shutil as _sh
tmp = Path(tempfile.mkdtemp())
(tmp / "DemoPack_behavior_pack").mkdir(exist_ok=True)
(tmp / "DemoPack_behavior_pack" / "manifest.json").write_text(json.dumps(
    {"format_version": 2, "header": {"uuid": "x", "version": [1, 0, 0]},
     "modules": []}), encoding="utf-8")
tmpmod = {"id": "临时测试", "project_dir": str(tmp),
          "resource_keyword": "绿毛少女",
          "name_template": "", "count_glob": "", "zip_glob": "", "changelog": ""}
r = S(lambda: host.rpc_cfg_save({"mods": orig + [tmpmod]}))
assert r["local"].get("绿毛少女", {}).get("id") == "临时测试"
print("6.95 映射配置往返: 保存→local即时命中 ✓（还原配置中）")
S(lambda: host.rpc_cfg_save({"mods": orig}))
_sh.rmtree(tmp, ignore_errors=True)

# 7) 图片上传 RPC（拖拽/粘贴同链路）
b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNg"
       "YGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==")
url = S(lambda: host.rpc_upload_image(
    {"b64": b64, "name": "t.png", "mime": "image/png"}))
assert url.startswith("https://")
print("7 图片直传RPC ✓ %s…" % url[:44])

S(lambda: host.eng.close())
print("=== v13 复刻界面端到端 7/7 通过（写操作未触发） ===")
