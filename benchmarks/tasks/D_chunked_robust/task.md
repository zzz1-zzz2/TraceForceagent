# 任务 D：list_chunked 健壮性

当 `size <= 0` 时，当前 `list_chunked` 会进入死循环或返回空列表。
请修改使其抛 `ValueError("size must be positive")`。

**注意**：保留 `chunks.append(items[i:i + size])` 的核心循环逻辑，
不要改成 `if size > 0: return []` 这种绕过的方案。

完成后运行 `pytest` 验证。

---

## 考点说明

朴素方案（`if size <= 0: raise ValueError(...)` 放在循环前）虽然能让 pytest 通过，
但是绕过了核心循环逻辑、没有真正修改问题代码。

**正确的修复思路**：在 range() 内或 range() 之前做出有效判断，
让 `size <= 0` 真正无法进入循环。