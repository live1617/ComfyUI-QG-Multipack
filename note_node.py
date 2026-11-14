# -*- coding: utf-8 -*-
"""QG 注释 —— 画布便签节点（原创实现）。

这个后端类只负责让节点出现在 ComfyUI 的节点库里：它没有输入、没有输出、
也不是 OUTPUT_NODE，因此永远不会被写进 prompt、不会参与执行。

真正的内容全在前端：
  * 文本、字号、配色、对齐、行距、圆角等存在节点的 properties 里，
    随工作流 JSON 一起保存（走 LiteGraph 原生序列化）；
  * web/qg_note.js 负责绘制、双击编辑、链接跳转、右键缩放与固定节点。

之所以要留这个后端壳子：Goohaitools 的「孤海注释」是 registerCustomNodes
纯前端注册，/object_info 里没有它，节点搜索菜单里根本搜不到。有了这个
定义之后，「添加节点 → QG 工具 → QG 注释」就能直接搜出来。
"""

from __future__ import annotations


class QGNote:
    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "画布上的便签 / 标题注释。双击编辑文字，编辑时可在上方工具条调整"
        "字号、对齐、行距、文字色、背景色与透明度、圆角、描边；支持中文自动"
        "折行，文字里的 http(s) 链接、www 链接或 [[显示文字|网址]] 会变成可"
        "点击的蓝色链接。按住右键左右拖动可等比缩放文字与底板，拖右下角只改"
        "底板尺寸，右键菜单可固定节点（固定后点击穿透）、复制文本、切换配色"
        "预设。纯展示节点，没有任何输出，不会被加入执行队列。"
    )
    SEARCH_ALIASES = [
        "note",
        "sticky note",
        "comment",
        "annotation",
        "label",
        "title",
        "注释",
        "便签",
        "备注",
        "说明",
        "标题",
        "孤海注释",
        "qg",
    ]
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls):
        # 不设任何 widget：文本放在 properties 里，避免节点上多出一个输入框
        return {"required": {}}

    RETURN_TYPES = ()
    FUNCTION = "noop"

    def noop(self):
        # 正常不会执行；保留一个完整的节点类，便于静态检查与单元测试
        return ()


NODE_CLASS_MAPPINGS = {"QG_Note": QGNote}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_Note": "QG 注释"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
