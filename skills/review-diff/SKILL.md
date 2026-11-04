---
name: review-diff
description: 审阅当前改动（git diff），只挑问题不重写代码。Use this when 用户说"审一下"、"看看改了什么"、"review 一下"、"这段 diff 有没有问题"、"帮我看看改动"。
---

## 什么时候用

改完代码要提交、要交付，或者你想让人挑刺的时候。

## 步骤

1. 先跑 `python skills/review-diff/scripts/collect_diff.py --stat` 看改了哪些文件
2. 再跑 `python skills/review-diff/scripts/collect_diff.py` 拿完整 diff（脚本会截断到 400 行，避免撑爆上下文）
3. 按五条清单逐条检查：
   - 有没有改到不该改的文件（配置、生成物、别人的模块）
   - 有没有新增依赖（requirements / pyproject 的改动）
   - 有没有 `except: pass` 或裸 `except`
   - 测试有没有覆盖新分支（新增函数对应新增用例）
   - diff 里有没有调试残留（`print(`、`TODO`、`breakpoint()`）
4. 每个问题输出「文件:行 + 一句话 + 建议动作」

## 不要做什么

- 不要在 review 阶段自己改代码
- 不要复述 diff 内容，只报问题
- 不要把「没意见」写成一句空话 —— 五条清单要逐条有结论

## 五条清单怎么判

- **改到不该改的文件**：出现在 `dist/`、`build/`、`__pycache__`、`.env*`、别人负责的模块
- **新增依赖**：`requirements*.txt` / `pyproject.toml` 里出现新的 `+` 行（哪怕只是版本号变化）
- **except: pass**：`except:` 或 `except Exception:` 后直接 `pass`，问题被吞掉
- **测试覆盖**：改了 `.py` 逻辑却没有对应的 `test_*.py` 改动
- **调试残留**：`print(`、`TODO`、`breakpoint()`、注释掉的旧代码

## 输出格式（照这个写，不要自由发挥）

```
1. 改到不该改的文件：无
2. 新增依赖：requirements.txt:3 numpy==2.1.0（建议去掉）
3. except: pass：agent/stats.py:5（建议改成 raise 并保留上下文）
4. 测试覆盖：无
5. 调试残留：agent/stats.py:4 print("mean fallback", nums)
问题总数：3
```

## 怎么算做完了

- 五条清单逐条有结论（无问题写「无」）
- 问题总数与脚本统计出的可疑行数一致
- 每个问题都能定位到「文件:行」
