# 任务 A：修复 safe_divide

math_utils.py 中的 `safe_divide(a, b)` 在 b=0 时应该返回 0.0，
但当前实现会抛 `ZeroDivisionError`。

请修改 `src/math_utils.py` 使所有测试通过，然后运行 `pytest` 验证。