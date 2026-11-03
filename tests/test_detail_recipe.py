# -*- coding: utf-8 -*-
"""详情组装配方的离线自检（不连平台、不写任何东西）。

守住三条：
1. 配方字数 = 前缀 + 标题 + 图×2，且 ≤ DETAIL_BUDGET（线上 404 实测可完整保存）；
2. 重复执行不叠标题：无论旧详情末尾是老长标题「📢 26.10.26 更新日志（…）」还是
   新超短标题「📢26.10.26更新」，重新组装后标题只有一个，字数不涨；
3. 用 tests/live_detail_dump.html（线上回读实样）回放：重组结果字数与线上 404 一致。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import do_publish as DP  # noqa: E402
import publish_api as PA  # noqa: E402

HERE = Path(__file__).resolve().parent
URL = "https://x19.fp.ps.netease.com/file/test-placeholder"
LOG = ["90_更新日志_1.png", "90_更新日志_2.png"]
GAL = ["0%d_附魔详细介绍.png" % i for i in range(5, 13)]

INTRO = ('<p><strong style="background-color: red;"><em><u>—— 趣味附魔 ——</u></em></strong></p>'
         '<p><br></p><p><span>【趣味附魔】更多创意附魔，重塑冒险体验！</span></p><p><br></p>')

OLD_LONG = INTRO + ('<p><strong style="font-size:18px;">'
                    '📢 26.10.26 更新日志（新增80个附魔，共242个）</strong></p>'
                    + "".join('<p><img src="%s"></p>' % URL for _ in LOG))
NEW_SHORT = INTRO + DP.BANNER + "".join('<p><img src="%s"></p>' % URL for _ in LOG)


def assemble(html):
    prefix = DP.split_prefix(html)
    return prefix, DP.build_detail(prefix, LOG, GAL, lambda n: URL)


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    return cond


ok = True
for tag, html in (("老长标题", OLD_LONG), ("新超短标题", NEW_SHORT)):
    print("[%s]" % tag)
    prefix, built = assemble(html)
    ok &= check("前缀不含图片", "<img" not in prefix)
    ok &= check("标题只出现一次", built.count("📢") == 1, "📢×%d" % built.count("📢"))
    ok &= check("组装后 10 图", built.count("<img") == 10)
    expect = DP.editor_len(prefix) + DP.editor_len(DP.BANNER) + 20
    ok &= check("字数口径自洽", DP.editor_len(built) == expect,
                "%d == %d" % (DP.editor_len(built), expect))
    ok &= check("不超预算", DP.editor_len(built) <= DP.DETAIL_BUDGET,
                "%d/%d" % (DP.editor_len(built), DP.DETAIL_BUDGET))
    # 幂等：把组装结果再当输入跑一遍，字数与标题数都不能变
    p2, built2 = assemble(built)
    ok &= check("幂等（字数不变）", DP.editor_len(built2) == DP.editor_len(built),
                "%d -> %d" % (DP.editor_len(built), DP.editor_len(built2)))
    ok &= check("幂等（标题唯一）", built2.count("📢") == 1)

dump = HERE / "live_detail_dump.html"
if dump.exists():
    print("[线上实样回放 %s]" % dump.name)
    live = dump.read_text(encoding="utf-8")
    live_len = DP.editor_len(live)
    prefix, built = assemble(live)
    ok &= check("线上字数=404", live_len == 404, str(live_len))
    ok &= check("publish_api 同口径", PA.editor_len(live) == live_len,
                str(PA.editor_len(live)))
    ok &= check("前缀 372 字", DP.editor_len(prefix) == 372, str(DP.editor_len(prefix)))
    # 重组字数 = 线上字数 - 新旧横幅日期字符差（26.10.26→26.11.3 少 1 字）
    delta = len("26.10.26") - len(DP.BANNER_DATE)
    ok &= check("重组后仍 404", DP.editor_len(built) == live_len - delta,
                str(DP.editor_len(built)))
    ok &= check("重组后不超预算", DP.editor_len(built) <= DP.DETAIL_BUDGET,
                "%d/%d" % (DP.editor_len(built), DP.DETAIL_BUDGET))
    ok &= check("重组后仍 10 图", built.count("<img") == 10)

print("[publish_api 护栏]")
# 口径已知值：文本2 + 块级3（<p>×2、<br>×1）+ 图1 = 6
sample = '<p>ab<br></p><p><img src="%s"></p>' % URL
ok &= check("editor_len 已知值=6", PA.editor_len(sample) == 6, str(PA.editor_len(sample)))
s = PA.sanitize_detail_html('<b>加粗</b><B >注</B><br/><body>o</body>')
ok &= check("<b>全部转strong", "<b>" not in s and "<B" not in s and s.count("<strong") == 2, s)
ok &= check("不误伤 body/br", "<body>" in s and "<br/>" in s, s)
try:
    PA.validate_detail_html("<p>" + "a" * 500 + "</p>")
    ok &= check("超字数报错", False)
except PA.DetailValidationError:
    ok &= check("超字数报错", True)
try:
    PA.validate_detail_html('<p><img src="%s"></p>' % URL * 11)
    ok &= check("超图数报错", False)
except PA.DetailValidationError:
    ok &= check("超图数报错", True)
n, ln = PA.validate_detail_html(
    NEW_SHORT + "".join('<p><img src="%s"></p>' % URL for _ in GAL))
ok &= check("合法内容放行(10图)", n == 10 and ln <= DP.DETAIL_BUDGET,
            "%d图 %d字" % (n, ln))

print("\n=== %s ===" % ("全部通过" if ok else "存在失败项"))
sys.exit(0 if ok else 1)
