# -*- coding: utf-8 -*-
"""节点尺寸持久化：从工作流加载的节点不得被前端扩展改回默认大小。

ComfyUI 的加载顺序是 createNode()（跑 onNodeCreated）→ node.configure()
（把存档的 size 写回）。扩展若在**延迟回调**（setTimeout / requestAnimationFrame）
里 setSize，就一定晚于 configure，用户拉过的尺寸会被冲掉，表现就是
「调好大小 → 存盘 → 重新打开又变回默认」。

规则：延迟回调里的 setSize 必须被 _qgSizeFromWorkflow 守卫；
同步阶段（onNodeCreated 里）的 setSize 不必，因为 configure 随后会覆盖。
"""

import io
import os
import re
import sys

TOTAL = 0
FAILED = 0
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)


def read(rel):
    with io.open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


def check(name, ok, detail=""):
    global TOTAL, FAILED
    TOTAL += 1
    if ok:
        print("PASS " + name)
    else:
        FAILED += 1
        print("FAIL " + name + ((" | " + detail) if detail else ""))


def body_after(src, marker, span=400):
    """取 marker 之后的一段源码，用来判断某调用是否在守卫之内。"""
    i = src.find(marker)
    return "" if i < 0 else src[i:i + span]


def main():
    photokit = read("web/qg_photokit_zh.js")
    outfit = read("web/qg_id_photo_outfit.js")

    print("== 一、QG.photokit.zh（6 个证件照节点共用的宽度贴合） ==")

    check("photokit 包装了 onConfigure",
          "nodeType.prototype.onConfigure" in photokit)
    check("photokit onConfigure 打上 _qgSizeFromWorkflow 标记",
          bool(re.search(r"onConfigure[\s\S]{0,300}_qgSizeFromWorkflow\s*=\s*true",
                         photokit)))
    # fit 是延迟回调，第一句就得不干活
    guard = re.search(r"const fit = \(\) => \{\s*try \{\s*if \(self\._qgSizeFromWorkflow\)\s*return;",
                      photokit)
    check("photokit fit() 第一句就是 _qgSizeFromWorkflow 守卫", bool(guard))
    check("photokit 守卫出现在 setSize 之前",
          photokit.find("if (self._qgSizeFromWorkflow) return;")
          < photokit.find("self.setSize([width, height])")
          if "self.setSize([width, height])" in photokit else False)
    check("photokit 仍然保留两处 setTimeout(fit, ...)",
          photokit.count("setTimeout(fit") == 2,
          "实际 %d 处" % photokit.count("setTimeout(fit"))
    check("photokit 宽度仍是「只增不减」",
          "Math.max(self.size[0], spec.width)" in photokit)
    check("photokit 已删掉「把旧高度缩回去」的旧注释",
          "gets shrunk here too" not in photokit)

    print("\n== 二、QG.IDPhotoOutfit（自带画廊的服装节点） ==")

    check("outfit 包装了 onConfigure",
          "nodeType.prototype.onConfigure" in outfit)
    check("outfit onConfigure 打上 _qgSizeFromWorkflow 标记",
          bool(re.search(r"onConfigure[\s\S]{0,300}_qgSizeFromWorkflow\s*=\s*true",
                         outfit)))
    tail = body_after(outfit, "setTimeout(() => {", 900)
    check("outfit 延迟回调先判 _qgSizeFromWorkflow",
          tail.find("_qgSizeFromWorkflow") >= 0
          and tail.find("_qgSizeFromWorkflow") < tail.find("node.setSize"),
          tail[:160].replace("\n", " "))
    check("outfit 的 setSize 在守卫之内（!node._qgSizeFromWorkflow）",
          "if (!node._qgSizeFromWorkflow)" in tail)
    check("outfit 仍按当前高度刷新画廊可视区",
          "updateGalleryHeight()" in tail)
    check("outfit 删掉了「首次打开时固定节点大小」的无条件写法",
          "首次打开时固定节点大小" not in outfit)

    print("\n== 三、全局：其余 setSize 属于同步阶段，不受影响 ==")

    for name in ("web/qg_marriage_cloth.js", "web/qg_translate.js",
                 "web/qg_qwen_prompt_optimizer.js"):
        src = read(name)
        check("%s 不在 setTimeout 里 setSize" % name.rsplit("/", 1)[-1],
              not re.search(r"setTimeout\([^)]*setSize", src))

    print("\n== 四、QG_QwenTextEncode（尺寸自带一份记录兜底） ==")

    text_enc = read("web/qg_qwen_text_encode.js")
    check("声明了尺寸记录属性名",
          'SIZE_PROPERTY = "qg_qwen_text_size"' in text_enc)
    check("保存时把尺寸写进节点数据（onSerialize，不是 onResize）",
          "onSerialize = function (data)" in text_enc
          and "data.properties[SIZE_PROPERTY]" in text_enc)
    check("onSerialize 包装在实例上（原型会被实例属性屏蔽）",
          "function hookSerialize(node)" in text_enc
          and "node.onSerialize = function (data)" in text_enc)
    check("加载后延迟校验并恢复尺寸",
          "function restoreSize(node)" in text_enc
          and "scheduleRestore(this)" in text_enc)
    check("恢复注册在 image 口同步之后（同帧内顺序固定）",
          text_enc.find("scheduleSync(this);\n            scheduleRestore(this);") >= 0
          or text_enc.find("scheduleSync(this);") < text_enc.find("scheduleRestore(this);"))
    # 新版前端把 size 存成类型化数组，Array.isArray 会漏判
    check("尺寸解析不依赖 Array.isArray（兼容类型化数组）",
          "Array.isArray(value)" not in text_enc
          and "typeof value.length !== \"number\"" in text_enc)
    check("恢复时不小于内容所需尺寸",
          "node.computeSize?.([saved[0], saved[1]])" in text_enc
          and "Math.max(targetW, pair[0])" in text_enc)
    check("恢复过程有重入保护",
          "node._qgRestoringSize = true" in text_enc)
    check("该节点仍然没有无条件 setSize 覆盖用户尺寸",
          not re.search(r"onResize[\s\S]{0,80}setSize\(\[", text_enc))

    print("\n== 五、QG_QwenPromptOptimizer（提示词高度记录，实例钩子） ==")

    opt = read("web/qg_qwen_prompt_optimizer.js")
    # 新版前端 node.size 是 Float64Array，Array.isArray 恒 false → 判据失灵
    check("尺寸判据不依赖 Array.isArray（兼容类型化数组）",
          "Array.isArray(node.size)" not in opt
          and "function sizePair(value)" in opt
          and "typeof value.length !== \"number\"" in opt)
    # addDOMWidget 会给实例挂 own onResize，只包原型会被整段屏蔽
    check("onResize 挂在实例上（不是只包 nodeType.prototype）",
          "function hookResize(node)" in opt
          and "node.onResize = function (size)" in opt
          and "hookResize(this)" in opt)
    check("保存时兜底把高度写进 properties",
          "function hookSerialize(node)" in opt
          and "node.onSerialize = function (data)" in opt
          and "data.properties[PROMPT_HEIGHT_PROPERTY]" in opt)
    check("缺记录时先从当前节点高度反推，不直接压回半高",
          "derivedHeight" in opt
          and "currentSize[1] - layout.fixedNodeHeight" in opt)
    check("该节点没有无条件 setSize 覆盖宽度",
          "node.setSize?.([currentSize ? Math.max(1, currentSize[0]) : 1, expectedHeight])" in opt)

    print("\n===== 合计 %d 项，FAIL %d =====" % (TOTAL, FAILED))
    return 1 if FAILED else 0

if __name__ == "__main__":
    sys.exit(main())
