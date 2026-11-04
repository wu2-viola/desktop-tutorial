# 项目地图

agent/loop.py　智能体循环：决策 → 工具 → 观察；三道护栏在这里
agent/tools/　四个工具（read / write / edit / bash），改这里要同步改 description
agent/skills.py　技能目录与按需加载（渐进披露）
agent/hooks.py　Pre/Post hook：拦密钥与危险命令，写完自动跑测试
agent/subagents.py　reviewer 子 agent（只读、只回结论）
agent/inspect.py　验收命令入口：skills / custom / daemon 三份 JSON
server/app.py　FastAPI 后端，SSE 事件流；ui/ 是纯静态，不经构建
skills/　技能目录，一个技能一个文件夹，可带走
workspace/　沙箱根目录，所有文件操作都要过 ToolContext.resolve_in_workspace()

# 构建与测试

python -m pytest tests -q                # 不要 -v，输出太长
python -m agent.inspect skills --out skill_report.json
python -m agent.inspect custom --out custom_report.json

# 代码风格

- 只用标准库 + fastapi + openai + pywebview，不引新依赖
- 错误一律返回 {"ok": false, "output": "<下一步做什么>"}，不要 except: pass
- 工具返回的 output 是写给模型看的：说清「发生了什么、下一步怎么做」
- 中文用于文档与界面文案，代码标识符与日志用英文

# 测试说明

- 全套 46+ 条，20 秒内跑完；慢的是 bash 超时与 MCP 子进程
- 测试用 tmp_path 隔离，不要写死绝对路径
- 红的常见原因：Windows 上 `ls` 不存在、pytest 收集失败、MCP 子进程没起

# 安全约束

- 不写 .env / *.pem / *.key：密钥只进用户目录，用环境变量
- 不跑 rm -rf / git push --force / git reset --hard
- 前端永远拿不到明文 Key，任何接口只回掩码

# 栈特定坑

- Windows + Python 3.12：路径分隔符、编码（统一 UTF-8）、控制台无 `ls`
- 演示工作区 workspace/stats.py 故意留了一个 bug（mean 对空列表返回 0），别顺手修掉
- edit 前必须先 read 同一文件，否则工具会拒绝（防止基于臆测的修改）
- 打包后资源在 sys._MEIPASS，写入一律走 Path.home()
