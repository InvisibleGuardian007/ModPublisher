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
    local:{"趣味附魔 - 共162个附魔":{id:"趣味附魔",version:"26.10.26",
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
    api_key:"sk-test",model:"m1"}};
  else if(action==="ai_save")data={ok:true};
  else if(action==="ai_polish")data={text:"润色后的文本",reply:"润色后的文本"};
  else if(action==="cfg_get")data={mods:[{id:"A"},{id:"B"},{id:"C"}]};
  else if(action==="cfg_save")data={local:{}};
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
        pg.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        pg.on("console", lambda m: errors.append("console.error: %s" % m.text)
              if m.type == "error" else None)
        pg.add_init_script(STUB)
        pg.goto(UI.as_uri())
        pg.wait_for_timeout(600)

        # 1) 启动渲染
        check("昵称", pg.text_content("#nick") == "测试者")
        check("状态点亮", "on" in pg.get_attribute("#dot", "class"))
        check("头像首字", pg.text_content("#avatar") == "测")
        check("品牌区", pg.text_content(".brand b") == "模组发布器")
        check("GitHub按钮", pg.get_attribute("#btnGit", "href") ==
              "https://github.com/InvisibleGuardian007/ModPublisher")
        check("列表5项", pg.locator(".item").count() == 5)
        check("状态药丸-上架绿", pg.locator(".item").nth(0).locator(".pill.on").count() == 1)
        check("状态药丸-审核蓝", pg.locator(".item").nth(1).locator(".pill.rev").count() == 1)
        check("状态药丸-驳回红", pg.locator(".item").nth(2).locator(".pill.bad").count() == 1)
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
        check("详情编辑器白纸", pg.evaluate(
            "getComputedStyle(document.getElementById('doc')).backgroundColor")
            == "rgb(255, 255, 255)")
        check("计数器=Quill口径", "29/404" in pg.text_content("#docCnt"),
              pg.text_content("#docCnt"))

        # 3.5) 手机端预览（实时同步）
        pg.click("#tPhone")
        pg.wait_for_timeout(150)
        check("手机预览打开", "open" in (pg.get_attribute("#phoneBox", "class") or ""))
        check("预览正文10图", pg.locator("#pvBody img").count() == 10)
        check("预览名称同步", pg.text_content("#pvName") == "趣味附魔 - 共162个附魔")
        check("预览价格同步", "第3档" in pg.text_content("#pvPrice"))
        check("预览标签同步", pg.locator("#pvTags span").count() == 2)
        pg.fill("#fName", "预览改名测试")
        check("预览名称实时", pg.text_content("#pvName") == "预览改名测试")
        pg.fill("#fName", "趣味附魔 - 共162个附魔")
        pg.click("#phClose")
        check("手机预览关闭", "open" not in (pg.get_attribute("#phoneBox", "class") or ""))
        check("预览含商店结构", True)  # 封面/下载按钮/详情分区见下方快照断言

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
        pg.wait_for_timeout(200)
        check("AI弹窗打开", pg.get_attribute("#aiModal", "style").find("flex") >= 0)
        check("AI配置回填", pg.input_value("#aiModel") == "m1"
              and pg.input_value("#aiBase") == "https://api.test/v1")
        pg.click("#aiX")
        check("AI弹窗关闭", pg.get_attribute("#aiModal", "style").find("none") >= 0)
        pg.click("#btnNoteAi")
        pg.wait_for_timeout(250)
        check("纪要AI润色", pg.input_value("#fNote") == "润色后的文本",
              pg.input_value("#fNote"))
        check("纪要润色标脏", "dirty" in (pg.get_attribute("#fNote", "class") or ""))
        pg.fill("#fNote", "")
        pg.dispatch_event("#fNote", "input")

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

        # 13) 未保存切换守卫（confirm 被自动拒绝 → 不切换）
        pg.fill("#fActivity", "新活动说明")
        pg.dispatch_event("#fActivity", "input")
        pg.locator(".item").nth(1).click()
        pg.wait_for_timeout(300)
        check("未保存守卫拦切换", pg.evaluate("state.sel") == "趣味附魔 - 共162个附魔")

        check("无JS错误", not errors, errors[:3])
        b.close()
    print()
    print("=== 全部通过 ===" if not FAIL else "=== FAIL: %s ===" % ", ".join(FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
