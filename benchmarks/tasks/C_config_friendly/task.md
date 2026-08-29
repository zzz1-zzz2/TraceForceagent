# 任务 C：让配置加载更友好

当前 `load_config` 在文件缺失或字段不全时直接崩溃。请改进它，
使其在以下情况更健壮：

- 配置文件不存在 → 返回 `{}`
- 配置文件缺少字段 → 补默认值

**Defaults**: `port=8080`, `host="localhost"`, `debug=false`

完成后运行 `pytest` 验证。