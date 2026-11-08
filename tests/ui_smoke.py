# -*- coding: utf-8 -*-
"""ui.html 离线冒烟：无头 Edge + 桩 __pyRequest（假数据），不连平台、不写配置。

覆盖：启动渲染 / 作品选择 / Quill口径计数器 / 规范键脏值跟踪 / 改动徽标 /
一键保存全链路（含基线同步）/ 状态药丸 / 搜索空态 / 主题切换与暗色可读性 /
映射弹窗 / 日志抽屉 / 进度浮层（确定+不确定态）/ 快捷键（Ctrl+S、/、Esc）。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
UI = Path(__file__).resolve().parent.parent / "ui.html"

DETAIL_HTML = ("<p>介绍文本测试</p><p><br></p>"
               + "".join('<p><img src="https://x/img%d.png"></p>' % i
                         for i in range(10)))
FIELDS = {k: "v" + k for k in
          ("item_name", "item_id", "item_version", "mod_id", "vanity_number",
           "status", "category", "mod_version", "mc_version", "author_info",
           "tag", "multi_tags", "searchable", "is_recommend",
           "price", "price_type", "price_rank", "charge_type",
           "info", "brief", "pe_game_introduction", "update_summary",
           "current_change_log", "activity_desc",
           "is_sync", "sync_pc_flag", "vip_only", "is_original", "banner_pic",
           "collection_id", "extra_unknown_field")}
FIELDS.update({"price": 3, "is_recommend": True})

ROWS = [
    {"name": "趣味附魔 - 共162个附魔", "rid": "1001", "category": "add_ons",
     "publish": "2026-10-26 12:00:00", "submit_at": "2026-10-26 13:00:00",
     "status": "已上架"},
    {"name": "僵尸启示录：起源 - 共计10只新僵尸", "rid": "1002",
     "category": "add_ons", "publish": "", "submit_at": "",
     "status": "审核中"},
    {"name": "头颅不仅仅是装饰品", "rid": "1003", "category": "add_ons",
     "publish": "", "submit_at": "", "status": "未通过"},
    {"name": "测试未上架作品", "rid": "1004", "category": "add_ons",
     "publish": "", "submit_at": "", "status": "未上架"},
    {"name": "测试草稿作品", "rid": "1005", "category": "add_ons",
     "publish": "", "submit_at": "", "status": ""},
]

STUB = """(()=>{window.__pyRequest=(action,payloadJson,id)=>{
  const P=action==="boot"?{}:JSON.parse(payloadJson||"{}");
  let data;
  if(action==="boot")data={
    profile:{nickname:"测试者",avatar:null},
    rows:%(rows)s,
    local:{"趣味附魔 - 共162个附魔":{id:"趣味附魔",version:"26.99.1",
      count:162,name_suggest:"趣味附魔 - 共242个附魔",
      note_suggest:"26.10.26更新：新增10个附魔；修复若干问题"}}};
  else if(action==="read_item")data={
    fields:%(fields)s,
    banner_pic:"https://x/banner.png",
    channels:[{id:1,url:"https://x/c1.png"},{id:2,url:""}],
    pc_channels:[{id:1001,url:""}],
    video:{url:"https://x/v.mp4",cover:"https://x/cov.jpg",size:2097152},
    guides:[{title:"攻略A",status:1},{title:"攻略B",status:0}],
    name:"趣味附魔 - 共162个附魔",mod_code:"12345",res_version:"26.10.26",
    price:"第3档 30钻",zip:"Enchant_2026-10-26_12-00-00.zip",
    tags:["趣味","附魔"],activity:"活动说明",pc_intro:"PC侧简介",
    note:"请到详细界面查看",
    detail_html:%(detail)s,detail_key:"pe_game_introduction"};
  else if(action==="publish")data={res_version:"26.11.08",zip:"new_2026.zip",
    detail_len:9,detail_imgs:10};
  else if(action==="upload_image")data="https://x/uploaded.png";
  else if(action==="ai_get")data={ai:{base_url:"https://api.test/v1",
    api_key:"sk-test",model:"m1"},
    ai_image:{base_url:"",api_key:"",model:"img1"}};
  else if(action==="ai_save")data={ok:true};
  else if(action==="ai_polish")data={text:"润色后的文本",reply:"润色后的文本"};
  else if(action==="ai_image")data={b64:"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    +"AAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==",mime:"image/png"};
  else if(action==="slot_save"||action==="pc_slot_save")data={url:"https://x/slot.png"};
  else if(action==="cfg_get")data={mods:[{id:"A"},{id:"B"},{id:"C"}]};
  else if(action==="app_info")data={version:"26.11.9",
    repo:"https://github.com/InvisibleGuardian007/ModPublisher",
    phone:"http://192.168.1.5:8765/ui?token=abc123"};
  else if(action==="check_update")data={current:"26.11.9",
    latest:localStorage.getItem("t_upd")?"26.12.0":"26.11.9",
    has_update:!!localStorage.getItem("t_upd"),
    asset:{name:"网易模组发布器.exe",url:"https://x/exe",size:1,
      digest:"sha256:x"},
    url:"https://github.com/InvisibleGuardian007/ModPublisher/releases/latest"};
  else if(action==="do_update")data={restarting:true,version:"26.12.0"};
  else if(action==="app_install")data={steps:["程序已复制","快捷方式已创建"],
    exe:"C:/x/网易模组发布器.exe",installed:true};
  else if(action==="cfg_save")data={local:{}};
  else if(action==="phone_preview")data={png:"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    +"AAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=="};
  else data={ok:true};
  setTimeout(()=>window.__pyResolve(id,JSON.stringify({ok:true,data:data})),10);}})()
""" % {"rows": json.dumps(ROWS, ensure_ascii=False),
       "fields": json.dumps(FIELDS, ensure_ascii=False),
       "detail": json.dumps(DETAIL_HTML)}

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  " + str(detail)) if detail else ""))
    if not cond:
        FAIL.append(name)


def main():
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        pg = b.new_page()
        dialog_ok = {"v": True}   # confirm 统一处理；守卫用例临时置 False
        pg.on("dialog", lambda d: d.accept() if dialog_ok["v"] else d.dismiss())
        pg.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        pg.on("console", lambda m: errors.append("console.error: %s" % m.text)
              if m.type == "error"
              and not ("Failed to load resource" in m.text
                       or "ERR_" in m.text) else None)
        pg.add_init_script(STUB)
        pg.goto(UI.as_uri())
        pg.wait_for_timeout(600)

        # 1) 启动渲染
        check("昵称", pg.text_content("#nick") == "测试者")
        check("状态点亮", "on" in pg.get_attribute("#dot", "class"))
        check("头像首字", pg.text_content("#avatar") == "测")
        check("品牌区已移除", pg.locator(".brand").count() == 0)
        check("GitHub按钮", pg.get_attribute("#btnGit", "href") ==
              "https://github.com/InvisibleGuardian007/ModPublisher")
        check("列表5项", pg.locator(".item").count() == 5)
        check("状态药丸-上架绿", pg.locator(".item").nth(0).locator(".pill.on").count() == 1)
        check("状态药丸-审核蓝", pg.locator(".item").nth(1).locator(".pill.rev").count() == 1)
        check("状态药丸-驳回红", pg.locator(".item").nth(2).locator(".pill.bad").count() == 1)
        check("登录按钮状态化", "ghost" in (pg.get_attribute("#btnLogin", "class") or "")
              and "重新登录" in pg.text_content("#btnLogin"))
        check("本地标记", pg.locator(".item").nth(0).locator(".pill.loc").count() == 1)
        check("欢迎空态显示", pg.locator("#welcome").is_visible())
        check("编辑区隐藏", not pg.locator("#editor").is_visible())

        # 2) 选中 → 表单/编辑器/槽位
        pg.locator(".item").nth(0).click()
        pg.wait_for_timeout(300)
        check("资源名称", pg.input_value("#fName") == "趣味附魔 - 共162个附魔")
        check("欢迎空态隐藏", not pg.locator("#welcome").is_visible())
        check("编辑区显示", pg.locator("#editor").is_visible())
        check("卡片图标徽章", pg.locator(".card h3 .ic").count() >= 7)
        check("版本徽章", "26.10.26" in pg.text_content("#fRo"))
        check("包徽章", "Enchant_2026" in pg.text_content("#fRo"))
        check("标签胶囊x2", pg.locator("#fTags .chip.tag").count() == 2)
        check("定价胶囊", "第3档" in pg.text_content("#fPrice"))
        check("攻略胶囊x2", pg.locator("#fGuides .chip.guide").count() == 2)
        check("PC简介并入纪要卡", pg.locator("#fPcIntro").is_visible())
        check("本地领先提示", "本地版本领先" in pg.text_content("#iteminfo"),
              pg.text_content("#iteminfo"))
        check("详情编辑器白纸", pg.evaluate(
            "getComputedStyle(document.getElementById('doc')).backgroundColor")
            == "rgb(255, 255, 255)")
        check("计数器=Quill口径", "29/404" in pg.text_content("#docCnt"),
              pg.text_content("#docCnt"))

        # 3.5) 手机端预览（网易平台自带预览实拍）
        pg.click("#tPhone")
        pg.wait_for_timeout(300)
        check("手机预览打开", "open" in (pg.get_attribute("#phoneBox", "class") or ""))
        check("平台实拍图就绪", "data:image/png" in (pg.get_attribute("#pvShot", "src") or "")
              and pg.locator("#pvShot").is_visible())
        check("加载态收敛", not pg.locator("#pvLoad").is_visible())
        pg.click("#pvShot")
        pg.wait_for_timeout(150)
        check("点击放大灯箱", "open" in (pg.get_attribute("#pvZoom", "class") or ""))
        pg.click("#pvZoom")
        pg.wait_for_timeout(150)
        check("灯箱关闭", "open" not in (pg.get_attribute("#pvZoom", "class") or ""))
        pg.click("#phRefresh")
        pg.wait_for_timeout(300)
        check("刷新后仍实拍", "data:image/png" in (pg.get_attribute("#pvShot", "src") or ""))
        pg.click("#phClose")
        check("手机预览关闭", "open" not in (pg.get_attribute("#phoneBox", "class") or ""))

        # 3.7) ✏️ 跳转高级字段
        pg.evaluate("document.querySelectorAll('.editlink')[0].click()")
        pg.wait_for_timeout(400)
        det_open = pg.evaluate(
            "document.querySelector('#content details').open")
        check("✏️展开高级区", det_open is True)
        pg.evaluate("document.querySelector('#content details').removeAttribute('open')")

        # 3.75) 卡片折叠（右上角箭头/点标题）
        pg.evaluate("document.querySelectorAll('#content .card h3')[0].click()")
        check("卡片可折叠", not pg.locator("#fName").is_visible())
        check("折叠箭头旋转", "folded" in (pg.locator("#content .card").nth(0)
              .get_attribute("class") or ""))
        pg.evaluate("document.querySelectorAll('#content .card h3')[0].click()")
        check("卡片可展开", pg.locator("#fName").is_visible())

        # 3.8) 编辑器全屏模式（⛶ / Esc 退出）
        dh0 = pg.evaluate("document.getElementById('doc').getBoundingClientRect().height")
        pg.click("#tFull")
        dh = pg.evaluate("document.getElementById('doc').getBoundingClientRect().height")
        check("编辑器全屏", dh > dh0 * 1.4, (dh0, dh))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(120)
        dh2 = pg.evaluate("document.getElementById('doc').getBoundingClientRect().height")
        check("全屏Esc退出", dh2 < 600, dh2)
        check("计数器图数", "10/10" in pg.text_content("#docCnt"))
        check("详情10图", pg.locator("#doc img").count() == 10)
        check("槽位=1ICON+2手机+1PC", pg.locator("#slots .slot").count() == 4)
        check("ICON现图", pg.locator("[data-slot='banner'] img").count() == 1)
        check("现存视频", (pg.locator("#vNow video").get_attribute("src") or "")
              .startswith("https"))
        check("攻略列表", "攻略A" in pg.text_content("#fGuides"))
        check("全字段渲染", pg.locator("#allfields .fitem").count() >= 31)
        pg.evaluate(
            "document.querySelector('#content details').setAttribute('open','')")
        pg.wait_for_timeout(100)
        pg.fill("#afKw", "price")
        n_price = pg.locator("#allfields .fitem").count()
        check("字段过滤price", 0 < n_price < 5, n_price)
        check("过滤计数提示", "显示" in pg.text_content("#afCnt"),
              pg.text_content("#afCnt"))
        pg.fill("#afKw", "")
        check("过滤清空还原", pg.locator("#allfields .fitem").count() >= 31)
        # 字段级 AI 改写（首个字符串字段的 ✨）
        pg.locator("#allfields .fitem .fk .editlink").first.click()
        pg.wait_for_timeout(250)
        check("字段AI改写", pg.locator("#allfields .fitem input").first
              .input_value() == "润色后的文本")
        check("底栏作品名", "趣味附魔" in pg.text_content("#barMod"))

        # 3) 规范键脏值跟踪 + 改动徽标
        pg.fill("#fName", "趣味附魔 - 共242个附魔")
        pg.dispatch_event("#fName", "input")
        check("输入即标绿", "dirty" in (pg.get_attribute("#fName", "class") or ""))
        check("脏值=规范键 item_name", pg.evaluate(
            "Object.keys(state.dirty).join()==='item_name'"))
        check("改动徽标可见", pg.text_content("#dirtyBadge") == "改动 1")

        # 4) Ctrl+S 一键保存全链路（桩 publish）→ 基线同步清脏
        pg.keyboard.press("Control+s")
        pg.wait_for_timeout(300)
        check("保存成功提示", "已保存" in pg.text_content("#msg"), pg.text_content("#msg"))
        check("保存后脏值清空", pg.evaluate("Object.keys(state.dirty).length") == 0)
        check("保存后徽标隐藏", pg.get_attribute("#dirtyBadge", "style").find("none") >= 0)
        check("保存后基线=新名", pg.evaluate("state.base.item_name") ==
              "趣味附魔 - 共242个附魔")
        check("版本回显", "26.11.08" in pg.text_content("#fRo"))
        check("zip回显", "new_2026.zip" in pg.text_content("#fZip"))

        # 4.5) AI 助手：配置弹窗回填 + 纪要润色（桩；放保存后避免污染脏值断言）
        pg.click("#btnAI")
        pg.wait_for_timeout(250)
        check("设置菜单打开", pg.get_attribute("#aiModal", "style").find("flex") >= 0)
        check("设置三个分项", pg.locator("#setMenu .set-item").count() == 3)
        pg.click("#setMenu .set-item >> nth=0")
        pg.wait_for_timeout(120)
        check("AI面板打开", pg.locator("#pAI").is_visible())
        check("AI配置回填", pg.input_value("#aiModel") == "m1"
              and pg.input_value("#aiBase") == "https://api.test/v1")
        pg.click("#pAI [data-back]")
        pg.wait_for_timeout(100)
        pg.click("#setMenu .set-item >> nth=1")
        pg.wait_for_timeout(120)
        check("生图面板+回填", pg.locator("#pImg").is_visible()
              and pg.input_value("#aiImgModel") == "img1")
        pg.click("#pImg [data-back]")
        pg.wait_for_timeout(100)
        pg.click("#setMenu .set-item >> nth=2")
        pg.wait_for_timeout(120)
        check("应用面板打开", pg.locator("#pApp").is_visible())
        check("版本显示", pg.text_content("#aboutVer") == "v26.11.9")
        check("手机端地址回填", "token=abc123" in pg.text_content("#webUrl"))
        pg.click("#btnCheckUpd")
        pg.wait_for_timeout(200)
        check("检查更新", "已是最新" in pg.text_content("#updTip"),
              pg.text_content("#updTip"))
        check("无更新时隐藏立即更新", not pg.locator("#btnDoUpdate").is_visible())
        # 热更新流：有新版 → 立即更新 → 重启安装（桩）
        pg.evaluate("localStorage.setItem('t_upd','1')")
        pg.click("#btnCheckUpd")
        pg.wait_for_timeout(200)
        check("发现新版显示更新按钮", pg.locator("#btnDoUpdate").is_visible()
              and "26.12.0" in pg.text_content("#btnDoUpdate"),
              pg.text_content("#btnDoUpdate"))
        check("设置红点", pg.evaluate(
            "document.getElementById('updDot').classList.contains('on')"))
        pg.click("#btnDoUpdate")
        pg.wait_for_timeout(200)
        check("热更新触发重启", pg.text_content("#btnDoUpdate") == "重启中…")
        pg.evaluate("localStorage.removeItem('t_upd')")
        # 应用内自安装（桩）
        pg.click("#btnAppInstall")
        pg.wait_for_timeout(200)
        check("自安装完成", "已安装" in pg.text_content("#btnAppInstall"),
              pg.text_content("#btnAppInstall"))
        pg.click("#aiX")
        check("AI弹窗关闭", pg.get_attribute("#aiModal", "style").find("none") >= 0)
        pg.click("#btnNoteAi")
        pg.wait_for_timeout(250)
        check("纪要AI润色", pg.input_value("#fNote") == "润色后的文本",
              pg.input_value("#fNote"))
        check("纪要润色标脏", "dirty" in (pg.get_attribute("#fNote", "class") or ""))
        pg.fill("#fNote", "")
        pg.dispatch_event("#fNote", "input")

        # 4.6) AI 生图：生成 → 插入详情 / 应用槽位（桩）
        pg.click("#btnGenSlots")
        check("生图弹窗打开",
              pg.get_attribute("#genModal", "style").find("flex") >= 0)
        pg.fill("#genPrompt", "可爱像素风附魔台")
        pg.click("#genGo")
        pg.wait_for_timeout(250)
        check("生图预览", pg.locator("#genImg").is_visible())
        check("生图操作区", pg.locator("#genActs").is_visible())
        pg.click("#genSlotsBtn")
        pg.wait_for_timeout(150)
        n_chips = pg.locator("#genSlotList button").count()
        check("槽位chips列表", n_chips == 4, n_chips)
        pg.locator("#genSlotList button").nth(0).click()
        pg.wait_for_timeout(300)
        check("生图应用槽位", (pg.get_attribute("[data-slot='banner'] img", "src")
              or "").startswith("https://x/slot.png"))
        before_doc = pg.locator("#doc img").count()
        pg.click("#btnGenDoc")
        pg.fill("#genPrompt", "红横幅")
        pg.click("#genGo")
        pg.wait_for_timeout(250)
        pg.click("#genToDoc")
        pg.wait_for_timeout(300)
        check("生图插入详情", pg.locator("#doc img").count() == before_doc + 1)

        # 5) 建议名称 / 生成纪要
        pg.click("#bName")
        check("建议名称填充", pg.input_value("#fName") == "趣味附魔 - 共242个附魔")
        pg.click("#bNote")
        check("纪要填充", "更新：" in pg.input_value("#fNote"))

        # 6) 字数超限警示（计数器变红）
        pg.evaluate("""()=>{const d=document.getElementById('doc');
          d.innerHTML='<p>'+'字'.repeat(500)+'</p>';
          d.dispatchEvent(new Event('input',{bubbles:true}))}""")
        check("超限计数变红", "over" in (pg.get_attribute("#docCnt", "class") or ""))
        check("超限提示保存被拦", True)  # 与下面 bRun 拦截合并验证
        pg.click("#bRun")
        pg.wait_for_timeout(200)
        check("保存护栏拦截", "超上限" in pg.text_content("#msg"), pg.text_content("#msg"))
        pg.evaluate("""()=>{const d=document.getElementById('doc');
          d.innerHTML='<p>恢复正常</p>';
          d.dispatchEvent(new Event('input',{bubbles:true}))}""")

        # 7) 搜索过滤 + 空态 + "/"聚焦
        pg.fill("#kw", "僵尸")
        check("搜索过滤", pg.locator(".item").count() == 1)
        pg.fill("#kw", "不存在的关键字xyz")
        check("搜索空态", pg.locator(".nores").count() == 1)
        pg.fill("#kw", "")
        pg.evaluate("document.activeElement.blur()")
        pg.keyboard.press("/")
        check("/ 聚焦搜索", pg.evaluate("document.activeElement.id") == "kw")

        # 8) 主题切换 + 暗色可读性
        bg1 = pg.evaluate("getComputedStyle(document.body).backgroundColor")
        pg.click("#btnTheme")
        time.sleep(0.2)
        bg2 = pg.evaluate("getComputedStyle(document.body).backgroundColor")
        check("主题切换背景变化", bg1 != bg2, (bg1, bg2))
        check("主题持久化", pg.evaluate("localStorage.getItem('mp_theme')") == "dark")
        check("暗色画布非白", pg.evaluate(
            "getComputedStyle(document.getElementById('doc')).backgroundColor")
            != "rgb(255, 255, 255)")
        pg.evaluate("""()=>{const s=document.createElement('span');
          s.style.color='#333';s.id='dkSpan';s.textContent='x';
          document.getElementById('doc').appendChild(s)}""")
        check("暗色内联深字反转", pg.evaluate(
            "getComputedStyle(document.getElementById('dkSpan')).color")
            == "rgb(231, 234, 243)")
        pairs = [("body", "backgroundColor", "color"),
                 ("#fName", "backgroundColor", "color"),
                 ("#doc", "backgroundColor", "color"),
                 ("#bar", "backgroundColor", "color"),
                 ("header", "backgroundColor", "color"),
                 ("aside", "backgroundColor", "color"),
                 (".search input", "backgroundColor", "color"),
                 (".mapcard-openlater", None, None)]
        bad = []
        for sel, bp, cp in pairs:
            if bp is None:
                continue
            bb = pg.evaluate(
                "getComputedStyle(document.querySelector('%s')).%s" % (sel, bp))
            cc = pg.evaluate(
                "getComputedStyle(document.querySelector('%s')).%s" % (sel, cp))
            if bb == cc:
                bad.append(sel)
        check("暗色可读性", not bad, bad)
        check("主题按钮文案", "深色" in pg.text_content("#btnTheme"))

        # 9) 映射弹窗 + Esc 关闭
        pg.click("#btnMap2")
        pg.wait_for_timeout(200)
        check("弹窗打开", pg.get_attribute("#mapModal", "style").find("flex") >= 0)
        check("映射3张卡", pg.locator("#mapList .mapcard").count() == 3)
        check("每卡7字段", pg.locator("#mapList .mapcard").nth(0)
              .locator(".grid > div").count() == 7)
        mcbg = pg.evaluate(
            "getComputedStyle(document.querySelector('.mapcard')).backgroundColor")
        check("暗色mapcard非白", mcbg not in ("rgb(248, 250, 252)", "rgb(255, 255, 255)"),
              mcbg)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(100)
        check("Esc关弹窗", pg.get_attribute("#mapModal", "style").find("none") >= 0)

        # 10) 日志抽屉（__mpLog → 抽屉 + 未读角标 + 分级配色）
        pg.evaluate("window.__mpLog('[引擎] 测试日志A')")
        pg.evaluate("window.__mpLog('[API] 测试日志B')")
        pg.evaluate("window.__mpLog('[API] 上传失败：超时')")
        check("未读角标", pg.get_attribute("#btnLog", "class").find("has") >= 0)
        pg.click("#btnLog")
        check("抽屉打开", "open" in (pg.get_attribute("#logBox", "class") or ""))
        check("日志行数", pg.locator("#logLines div").count() >= 3)
        check("API行蓝色", "api" in (pg.locator("#logLines div").nth(
              pg.locator("#logLines div").count() - 2).get_attribute("class") or ""))
        check("错误行红色", "err" in (pg.locator("#logLines div").last
              .get_attribute("class") or ""))
        pg.click("#logClose")
        check("抽屉关闭", "open" not in (pg.get_attribute("#logBox", "class") or ""))

        # 11) 进度浮层：确定 → 不确定 → 隐藏
        pg.evaluate(
            "window.__mpEvent('pack_progress',JSON.stringify({frac:0.5,msg:'打包50'}))")
        check("进度50%", pg.text_content("#progP") == "50%")
        pg.evaluate(
            "window.__mpEvent('pack_progress',JSON.stringify({frac:null,msg:'直传中…'}))")
        check("直传不确定态", "indet" in (pg.get_attribute("#prog", "class") or "")
              and pg.text_content("#progT") == "直传中…")
        pg.evaluate(
            "window.__mpEvent('pack_progress',JSON.stringify({frac:null,msg:''}))")
        check("浮层隐藏", pg.evaluate(
            "document.getElementById('prog').style.display") == "none")

        # 12) 视频槽位预览（本地对象URL）
        pg.evaluate("""async ()=>{
          const blob=await (await fetch('data:video/mp4;base64,AAAA')).blob();
          const dt=new DataTransfer();
          dt.items.add(new File([blob],'demo.mp4',{type:'video/mp4'}));
          const d=document.getElementById('vSlot');
          d.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true}))}""")
        pg.wait_for_timeout(200)
        check("视频预览+文件名", "demo.mp4" in pg.text_content("#vEmpty"),
              pg.text_content("#vEmpty"))

        # 13) 未保存切换守卫（confirm 拒绝 → 不切换）
        pg.fill("#fActivity", "新活动说明")
        pg.dispatch_event("#fActivity", "input")
        dialog_ok["v"] = False
        pg.locator(".item").nth(1).click()
        dialog_ok["v"] = True
        pg.wait_for_timeout(300)
        check("未保存守卫拦切换", pg.evaluate("state.sel") == "趣味附魔 - 共162个附魔")

        # 14) ⚙ 设置入口 + 窄窗自适应抽屉
        check("设置按钮", "设置" in pg.text_content("#btnAI"))
        pg.set_viewport_size({"width": 820, "height": 900})
        pg.wait_for_timeout(300)
        check("窄窗显示汉堡", pg.locator("#btnNav").is_visible())
        nav_t = pg.evaluate(
            "getComputedStyle(document.querySelector('aside')).transform")
        check("窄窗侧栏收起", nav_t not in ("none", ""), nav_t)
        pg.click("#btnNav")
        pg.wait_for_timeout(350)
        check("抽屉展开", "nav-open" in pg.evaluate("document.body.className"))
        aside_x = pg.evaluate(
            "document.querySelector('aside').getBoundingClientRect().left")
        check("抽屉滑入可视", aside_x == 0, aside_x)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        check("Esc收抽屉", "nav-open" not in pg.evaluate("document.body.className"))
        pg.click("#btnNav")
        pg.wait_for_timeout(300)
        pg.locator(".item").nth(1).click()
        pg.wait_for_timeout(300)
        check("选作品自动收抽屉",
              "nav-open" not in pg.evaluate("document.body.className"))
        pg.set_viewport_size({"width": 1366, "height": 950})
        pg.wait_for_timeout(300)
        check("宽窗汉堡隐藏", not pg.locator("#btnNav").is_visible())

        # 14.5) 手机 390：底栏折叠为「⋯ 更多」
        pg.set_viewport_size({"width": 390, "height": 844})
        pg.wait_for_timeout(300)
        check("手机更多按钮", pg.locator("#barMoreToggle").is_visible())
        check("次要操作默认收起", not pg.locator("#bName").is_visible())
        pg.click("#barMoreToggle")
        pg.wait_for_timeout(150)
        check("更多面板展开", "barmore" in pg.evaluate("document.body.className")
              and pg.locator("#bName").is_visible())
        pg.click("#barMoreToggle")
        pg.wait_for_timeout(150)
        check("更多面板收起", not pg.locator("#bName").is_visible())
        pg.set_viewport_size({"width": 1366, "height": 950})
        pg.wait_for_timeout(200)

        # 15) 登录门：未登录桩（第二页面）→ 品牌登录页；登录后进入
        stub2 = STUB.replace('profile:{nickname:"测试者",avatar:null}',
                             'profile:null')
        pg2 = b.new_page()
        pg2.add_init_script(stub2)
        pg2.goto(UI.as_uri())
        pg2.wait_for_timeout(500)
        check("登录门显示", pg2.locator("#loginGate").is_visible())
        check("登录门文案", "未登录" in pg2.text_content("#lgMsg"))
        check("登录按钮出现", pg2.locator("#lgGo").is_visible())
        check("版本角标", "26.11.9" in pg2.text_content(".lg-ver"))
        pg2.close()

        check("无JS错误", not errors, errors[:3])
        b.close()
    print()
    print("=== 全部通过 ===" if not FAIL else "=== FAIL: %s ===" % ", ".join(FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
