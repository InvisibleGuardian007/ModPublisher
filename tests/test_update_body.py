# -*- coding: utf-8 -*-
"""build_update_body 变更应用回归（离线，不连平台）。

守住的历史坑：changes 此前只透传 6 个白名单键，界面手改的
资源名称/纪要/PC简介/全字段/组件ICON 等改动会被**静默丢弃**。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import publish_api as PA  # noqa: E402

DETAIL = {
    "item_name": "趣味附魔 - 共162个附魔",
    "item_version": "26.10.26",
    "banner_pic": "https://old/banner.png",
    "mc_version": ["1.20"],
    "price": 2,
    "is_recommend": True,
    "note_str": "abc",
    "channel": [],
    "res": [{"res_name": "old.zip", "file_type": "zip_package"}],
    "sync_pc_flag": 0,
}
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


# 1) 非白名单键（ICON 槽位路径）真正生效
b = PA.build_update_body(DETAIL, {"banner_pic": "https://new/banner.png"})
check("banner_pic 变更生效", b["banner_pic"] == "https://new/banner.png",
      b["banner_pic"])

# 2) 界面全字段编辑：字符串脏值按原字段类型适配
b = PA.build_update_body(DETAIL, {"item_name": "新名", "price": "5",
                                  "is_recommend": "false",
                                  "mc_version": '["1.21","1.20"]'})
check("item_name 生效", b["item_name"] == "新名")
check("int 字段字符串→int", b["price"] == 5 and isinstance(b["price"], int))
check("bool 字段字符串→bool", b["is_recommend"] is False)
check("list 字段 JSON串→list", b["mc_version"] == ["1.21", "1.20"])

# 3) 无关键不越权：changes 为空时 body 与 detail 对齐
b = PA.build_update_body(DETAIL, {})
check("空 changes 不改值", b["item_name"] == DETAIL["item_name"]
      and b["mc_version"] == ["1.20"] and b["banner_pic"] == DETAIL["banner_pic"])

# 4) 专用通道键不进通用覆盖（new_res 走 res 组装）
b = PA.build_update_body(DETAIL, {"new_res": {"body": "{}", "sign": "s"},
                                  "new_res_name": "new.zip",
                                  "add_version": True})
check("new_res 组装进 res[0]", b["res"][0]["res_name"] == "new.zip"
      and b["res"][0]["add_version"] == 1)
check("body 不残留 new_res 顶层键", "new_res" not in b and "add_version" not in b)

# 5) channel 变更（JSON 串）生效
b = PA.build_update_body(DETAIL, {"channel": '[{"channel_id":1,"channel_url":"u"}]'})
check("channel JSON串→list", isinstance(b["channel"], list)
      and b["channel"][0]["channel_id"] == 1)

# 6) 纪要镜像由调用方负责；update_summary 截断由 _api_publish 处理（此处仅透传）
b = PA.build_update_body(DETAIL, {"update_summary": "修复若干问题"})
check("update_summary 生效", b["update_summary"] == "修复若干问题")

print()
print("=== 全部通过 ===" if not FAIL else "=== FAIL: %s ===" % ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
