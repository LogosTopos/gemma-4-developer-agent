# 12 个固定实验样本

人工选择的诊断集合；不是随机样本。参考位置和修改规模仅供研究者阅读，此文件不应进入模型上下文。

| ID | 主要考察 | 参考规模 | 修改位置 |
|---|---|---:|---|
| fastapi_15661 | 新增文件；发布脚本；规格不充分 | 216 行 / 1 文件 | `scripts/prepare_release.py` |
| fastapi_15589 | 模板噪声；请求头别名与输入验证 | 4 行 / 1 文件 | `fastapi/dependencies/utils.py` |
| requests_7502 | 短描述；动态属性与协议检测 | 4 行 / 1 文件 | `src/requests/models.py` |
| requests_7315 | 明确复现；URL 路径语义；两行修改 | 2 行 / 1 文件 | `src/requests/adapters.py` |
| rich_4006 | 描述依赖外链；Unicode 零宽字符 | 45 行 / 1 文件 | `rich/cells.py` |
| fastapi_14786 | 描述直接给出修复；适合作为提示上限样本 | 2 行 / 1 文件 | `fastapi/security/utils.py` |
| fastapi_14448 | 多文件；装饰器与同步异步调用 | 106 行 / 2 文件 | `fastapi/dependencies/models.py`, `fastapi/dependencies/utils.py` |
| httpx_3672 | 唯一 HTTPX 任务；同步异步多文件协议状态 | 79 行 / 7 文件 | `src/ahttpx/_parsers.py`, `src/ahttpx/_pool.py`, `src/ahttpx/_server.py`, `src/httpx/_network.py`, `src/httpx/_parsers.py`, `src/httpx/_pool.py`, `src/httpx/_server.py` |
| requests_6629 | 详细根因提示；异常序列化与继承 | 10 行 / 1 文件 | `src/requests/exceptions.py` |
| rich_3480 | 描述依赖外链；自引用与无限循环 | 4 行 / 1 文件 | `rich/text.py` |
| rich_3471 | 描述依赖外链；文本控制字符 | 1 行 / 1 文件 | `rich/text.py` |
| rich_3063 | 描述依赖外链；转义边界 | 4 行 / 1 文件 | `rich/markup.py` |

三个已确认的行为差异：Requests 应保留请求路径开头的双斜杠；Rich 应正确转义末尾反斜杠并保留文本样式；FastAPI 应移除 Authorization 参数两侧空白。其余样本仅完成静态与检索检查，未确认完整参考测试通过。
