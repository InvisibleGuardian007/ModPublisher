# -*- coding: utf-8 -*-
"""真实发布（优先附加到发布器已打开的 Edge，不另开浏览器）：
上传素材长图 → 组装详情 → 打包直传 → update 保存 → 打开作品列表供查看。
不含提审（提交需用户确认后另行执行）。

平台限制（2026-10-26 实测，口径＝Quill 编辑器字数，不是 HTML 字符长度）：
  · 纯文本每个字符 1 字；每个块级 <p> / <br> 各 1 字；每张图 1 字；
  · 上限≈405 字 —— 404 字实测可完整保存并回读（再高未验证，超了会**静默截断吞图**，不报错）；
  · 图片 ≤10 张；HTML 仅白名单标签（p/strong/span/br/img 可用，<b> 报"非法字符: bad tag: b"）。

已验证配方（线上回读实样见 tests/live_detail_dump.html）：
  红横幅前缀 372 字 + 超短标题「📢26.10.26更新」12 字 + 2 张更新日志长图 + 8 张图鉴长图（10×2=20 字）
  = 404 字，10 张图全部在线、一个不少。
  标题一旦写长（旧标题「📢 26.10.26 更新日志（新增80个附魔，共242个）」要 28 字），预算立刻不够，
  末尾的图被静默吞掉——这才是当初误判「图鉴长图放不进详情」的真因，不是平台不给放。

可重复执行：组装前会先把前缀末尾的历史更新标题（老长标题 / 新超短标题）裁掉，
所以一天跑多次不会叠出两个标题、也不会因此超字数。

用法：
  python tests/do_publish.py            # 真实发布：传图 → 组装 → 打包直传 → update 保存 → 回读校验
  python tests/do_publish.py --dry-run  # 只读自检：读平台现详情、按配方组装并报字数，不传图不保存
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import publish_api as PA  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

RIDD = "4686112979926756435"
NAME = "趣味附魔 - 共242个附魔"
IMGS = Path(__file__).resolve().parent / "pubimgs"
PROJECT = Path(r"D:/MCModDve/MoreEnchantments")
LOG = Path(__file__).resolve().parent / "publish_result.json"
CDP = "http://127.0.0.1:9222"

# —— 预算与配方（改版本时只需改 BANNER_DATE）——
DETAIL_BUDGET = 404        # 实测可完整保存的字数上限（平台≈405）
IMG_LIMIT = 10             # 平台详情图片上限
BANNER_DATE = "26.11.3"    # 与 更新日志.md 顶部标题、模组版本号保持一致
BANNER = "<p><strong>📢%s更新</strong></p>" % BANNER_DATE  # 12 字，别加长
DRY_URL = "https://x19.fp.ps.netease.com/file/dryrun-placeholder"

# PC 详情 = sync_item_info.info，与 PE 详情是两份独立富文本；
# 编辑器上限 1000 字（页面上标 x/1000），预算宽裕，用得下完整长标题
PC_BUDGET = 1000
PC_BANNER = ("<p><strong style=\"font-size:18px;\">📢 %s 更新日志"
             "（百科大升级，共242个）</strong></p>" % BANNER_DATE)  # 改版本时连同数字一起改

# 历史更新标题：老形态「📢 26.10.26 更新日志（新增80个附魔，共242个）」/ 新形态「📢26.10.26更新」
_UPDATE_TITLE = re.compile(r"^📢?\s*[0-9.]*\s*更新(日志)?.*$")


# Quill 字数口径统一在 publish_api.editor_len（tests/test_detail_recipe.py 有口径自检）
editor_len = PA.editor_len


def strip_trailing_update_title(prefix):
    """裁掉前缀**末尾**的历史更新标题，保证脚本可重复执行不叠标题。

    只从末尾往前剥（最多 4 段），命中「…更新日志…」或「📢…更新」就整段去掉；
    正文中间的「更新」字样不会被动到。
    """
    cut = prefix
    for _ in range(4):
        paras = list(re.finditer(r"<p[^>]*>.*?</p>", cut, re.S))
        if not paras or paras[-1].end() != len(cut):
            break
        text = re.sub(r"<[^>]+>", "", paras[-1].group(0)).strip()
        if not text or not _UPDATE_TITLE.match(text):
            break
        cut = cut[:paras[-1].start()]
    return cut


def split_prefix(html):
    """前缀 = 首图所在 <p> 之前的全部内容（不依赖文本锚点：线上详情可能是被截断过的任意形态），
    再把末尾历史更新标题裁掉。"""
    i_img = html.find("<img")
    if i_img >= 0:
        p_start = max(html.rfind("<p>", 0, i_img), html.rfind("<p ", 0, i_img))
    else:
        a_idx = html.find("以下是一些附魔的详细介绍")
        p_start = html.rfind("<p>", 0, a_idx) if a_idx > 0 else -1
    if p_start <= 0:
        raise RuntimeError("详情前缀定位失败")
    prefix = strip_trailing_update_title(html[:p_start])
    assert "<img" not in prefix, "前缀里混入了图片，定位异常"
    return prefix


def build_detail(prefix, log_imgs, gal_imgs, url_of):
    """按验证过的配方组装详情：前缀 + 超短标题 + 2 日志图 + 8 图鉴图"""
    names = list(log_imgs) + list(gal_imgs)
    assert names, "缺少素材长图，请先跑 gen_detail_images.py"
    assert len(names) <= IMG_LIMIT, "平台图片上限 %d 张，当前 %d 张" % (IMG_LIMIT, len(names))
    imgs = "".join('<p><img src="%s"></p>' % url_of(n) for n in names)
    return prefix + BANNER + imgs


def main(dry=False):
    out = {}
    with sync_playwright() as p:
        attached = False
        try:
            browser = p.chromium.connect_over_cdp(CDP, timeout=8000)
            ctx = browser.contexts[0]
            attached = True
            print("已附加到发布器 Edge（所有操作都在这个已打开的窗口里进行）", flush=True)
        except Exception as e:
            print("附加 9222 失败(%s)，本地另起" % e, flush=True)
            ctx = p.chromium.launch_persistent_context(
                str(Path(__file__).resolve().parent.parent / "dist" / "profile"),
                channel="msedge", headless=True)

        pg = ctx.new_page()
        pg.goto("https://mcdev.webapp.163.com/", wait_until="domcontentloaded")
        pg.wait_for_timeout(4000)
        api = PA.Api()
        api.set_context(ctx, page=pg)

        print("登录:", api.user_info()["nickname"], flush=True)

        detail = api.detail(RIDD)
        old_html, key = "", None
        for k in ("pe_game_introduction", "info"):
            v = detail.get(k) or ""
            if "<p>" in v or "<img" in v:
                old_html, key = v, k
                break
        if not old_html:
            raise RuntimeError("详情富文本字段为空")
        print("旧详情字段=%s 长度=%d 图片=%d 字数≈%d" % (
            key, len(old_html), old_html.count("<img"), editor_len(old_html)), flush=True)

        # 1) 前缀（红横幅+介绍文字），并裁掉末尾历史更新标题
        prefix = split_prefix(old_html)
        print("前缀字数≈%d | 尾部: %s" % (editor_len(prefix), prefix[-60:]), flush=True)

        # 2) 素材：2 张更新日志长图 + 8 张图鉴长图
        log_imgs = [f.name for f in sorted(IMGS.glob("90_更新日志_*.png"))]
        gal_imgs = [f.name for f in sorted(IMGS.glob("*_附魔详细介绍*.png"))]
        names = log_imgs + gal_imgs
        assert log_imgs and gal_imgs, "缺少素材长图，请先跑 gen_detail_images.py"
        assert len(names) <= IMG_LIMIT, "平台图片上限 %d 张，当前 %d 张" % (IMG_LIMIT, len(names))

        urls = {}
        if dry:
            print("[dry-run] 跳过上传，用占位 URL 组装（%d 张：%s）" % (
                len(names), ", ".join(names)), flush=True)
            new_html = build_detail(prefix, log_imgs, gal_imgs, lambda n: DRY_URL)
        else:
            for i, n in enumerate(names, 1):
                info = api.upload("image", IMGS / n, "image/png")
                urls[n] = json.loads(info["body"])["url"]
                print("上传 %d/%d %s" % (i, len(names), n), flush=True)
            new_html = build_detail(prefix, log_imgs, gal_imgs, lambda n: urls[n])

        n_img = new_html.count("<img")
        total = editor_len(new_html)
        print("配方核对：前缀 %d 字 + 标题 %d 字 + %d 图×2 = **%d 字**（预算 %d）" % (
            editor_len(prefix), editor_len(BANNER), n_img, total, DETAIL_BUDGET), flush=True)
        assert total <= DETAIL_BUDGET, (
            "详情 %d 字超预算 %d，会被静默截断吞图；先压前缀文字或缩短标题" % (total, DETAIL_BUDGET))

        # 2b) PC 详情（sync_item_info.info）：同一配方，预算 1000 字用长标题；
        #     只改 si["info"]，其余键原样保留；build_update_body 从 detail 透传
        si = detail.get("sync_item_info")
        si = dict(si) if isinstance(si, dict) else {}
        url_of_pc = (lambda n: DRY_URL) if dry else (lambda n: urls[n])
        si["info"] = (prefix + PC_BANNER
                      + "".join('<p><img src="%s"></p>' % url_of_pc(n) for n in names))
        pc_total = editor_len(si["info"])
        print("PC 详情：前缀 %d + 长标题 %d + %d 图×2 = %d 字（预算 %d）" % (
            editor_len(prefix), editor_len(PC_BANNER), len(names),
            pc_total, PC_BUDGET), flush=True)
        assert pc_total <= PC_BUDGET, "PC 详情 %d 字超预算 %d" % (pc_total, PC_BUDGET)
        detail["sync_item_info"] = si

        # 3) 更新纪要（≤200 字）
        md = (PROJECT / "更新日志.md").read_text(encoding="utf-8-sig")
        m = re.search(r"## 系统调整\n(.*?)\n##", md, re.S)
        items = [l.strip("- ").strip() for l in m.group(1).splitlines()
                 if l.startswith("- ")]
        note = "%s更新：%s" % (BANNER_DATE, "；".join(items))
        note = note[:199] + "…" if len(note) > 200 else note
        print("纪要(%d字): %s" % (len(note), note), flush=True)

        if dry:
            print(json.dumps({"dry_run": True, "detail_key": key,
                              "prefix_len": editor_len(prefix),
                              "detail_len": len(new_html), "editor_len": total,
                              "pc_editor_len": pc_total,
                              "imgs": n_img, "expect_imgs": len(names),
                              "note_len": len(note), "banner": BANNER},
                             ensure_ascii=False), flush=True)
            try:
                pg.close()
            except Exception:
                pass
            if not attached:
                ctx.close()
            print("=== --dry-run 自检完成（未上传、未保存、未提审） ===", flush=True)
            return None

        # 4) 打包（进度打印）+ 直传
        def prog(f, msg):
            print("  [%3d%%] %s" % (round(f * 100), msg), flush=True)

        z = PA.pack_project(PROJECT, progress=prog)
        print("zip:", z.name, "%.2fMB" % (z.stat().st_size / 1048576), flush=True)
        zinfo = api.upload("zip_package", z, "application/zip")
        print("zip直传完成 sign=%s…" % zinfo["sign"][:12], flush=True)

        # 5) update 保存
        changes = {
            "item_name": NAME,
            "update_summary": note,
            "current_change_log": note,
            key: new_html,
            "new_res": zinfo,
            "new_res_name": z.name,
            "add_version": True,
        }
        body = PA.build_update_body(detail, changes)
        api.update_item(RIDD, body)
        print("update 保存成功 ✓", flush=True)

        # 6) 重读验证（图片数必须一张不少，否则就是被截断了；PE/PC 都验）
        d2 = api.detail(RIDD)
        html2 = d2.get(key) or ""
        got = html2.count("<img")
        print("回读：图片 %d/%d、字数≈%d、HTML %d 字符 → %s" % (
            got, len(names), editor_len(html2), len(html2),
            "✓ 完整" if got == len(names) else "✗ 被截断！"), flush=True)
        si2 = d2.get("sync_item_info")
        si2 = si2 if isinstance(si2, dict) else {}
        pc2 = si2.get("info") or ""
        pc_got = pc2.count("<img")
        print("PC 回读：图片 %d/%d、字数≈%d → %s" % (
            pc_got, len(names), editor_len(pc2),
            "✓ 完整" if pc_got == len(names) else "✗ 被截断！"), flush=True)
        out = {
            "name": d2.get("item_name"),
            "version": d2.get("item_version"),
            "update_summary": d2.get("update_summary"),
            "detail_len": len(html2),
            "editor_len": editor_len(html2),
            "new_imgs_in_detail": got,
            "expect_imgs": len(names),
            "pc_editor_len": editor_len(pc2),
            "pc_imgs": pc_got,
            "res_name": (d2.get("res") or [{}])[0].get("res_name"),
            "zip_uploaded": z.name,
            "urls": urls,
        }
        print(json.dumps({k: v for k, v in out.items() if k != "urls"},
                         ensure_ascii=False, indent=1), flush=True)

        try:
            pg.close()
        except Exception:
            pass

        # 7) 复用窗口里已有的平台标签（优先登录页旧标签，其次任意 mcdev 标签），
        #    领到已登录的作品列表并带到前台，供直接查看效果
        try:
            target, list_url = None, "https://mcdev.webapp.163.com/#/work/list/pe_component"
            for pg2 in list(ctx.pages):
                if "#/login" in (pg2.url or ""):
                    target = pg2
                    break
            if target is None:
                for pg2 in list(ctx.pages):
                    if "mcdev.webapp.163.com" in (pg2.url or ""):
                        target = pg2
                        break
            if target is None:
                target = ctx.new_page()
            target.goto(list_url, wait_until="domcontentloaded")
            try:
                target.set_viewport_size({"width": 1360, "height": 960})
                target.bring_to_front()
            except Exception:
                pass
            print("平台页已带到作品列表（登录态正常）", flush=True)
        except Exception:
            pass

        if not attached:
            ctx.close()

    LOG.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== 发布保存流程完成（未提审） ===", flush=True)
    return out


if __name__ == "__main__":
    main(dry="--dry-run" in sys.argv[1:])
