# -*- coding: utf-8 -*-
"""publish_core.py 一次性重构 v2：平台自动化方法改用专用副页 self.wp。"""
import io
import re

P = "publish_core.py"
s = io.open(P, encoding="utf-8").read()

# 1) __init__ / close 增加 _work 字段（_editor_mod 行均已确认存在）
s = s.replace(
    "        self.page = None\n        self._editor_mod = None   # 当前停在编辑页的模组id",
    "        self.page = None          # 主应用窗口页（--app UI），自动化绝不占用\n"
    "        self._work = None         # 平台自动化专用副页\n"
    "        self._editor_mod = None   # 当前停在编辑页的模组id", 1)
n_close = s.count("        self.page = None\n        self._editor_mod = None\n")
s = s.replace(
    "        self.page = None\n        self._editor_mod = None\n",
    "        self.page = None\n        self._work = None\n        self._editor_mod = None\n")
print("close-replaced:", n_close)

# 2) wp 属性（log 方法后插入）
anchor = '    def log(self, msg):\n        self.emit("log", msg)\n'
assert anchor in s, "log anchor missing"
s = s.replace(anchor, anchor + '''
    @property
    def wp(self):
        """平台自动化专用页面：新建/复用隐藏副页，主应用窗口永不被导航。"""
        if self._work is None or self._work.is_closed():
            self._work = self._ctx.new_page()
            try:   # 副页会抢焦点：把主应用窗口带回前台
                self.page.bring_to_front()
            except Exception:
                pass
        return self._work

''', 1)

# 3) 自动化方法块内 self.page → self.wp
AUTO = {"logged_in", "read_profile", "_goto_list", "read_list", "open_editor",
        "read_current", "_mark_zip_input", "apply_and_save", "submit",
        "set_detail_html", "upload_detail_image"}
parts = re.split(r"(?m)^(    def |    @property)", s)
out = [parts[0]]
for i in range(1, len(parts), 2):
    head, body = parts[i], parts[i + 1]
    m = re.match(r"\s*def\s+(\w+)\(", head + body)
    if m and m.group(1) in AUTO:
        body = body.replace("self.page", "self.wp")
    out.append(head)
    out.append(body)
s = "".join(out)

io.open(P, "w", encoding="utf-8").write(s)
print("wp refs:", s.count("self.wp"))
