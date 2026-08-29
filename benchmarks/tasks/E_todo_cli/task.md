# 任务 E：从零实现 Todo CLI

在当前空目录从零构建一个命令行 Todo 工具，要求：

1. 支持四个子命令：
   - `add <text>`：添加一条 todo
   - `list`：列出所有 todo
   - `done <id>`：标记 id 对应的 todo 为完成
   - `remove <id>`：删除 id 对应的 todo

2. 数据持久化到 `todos.json`

3. 提供 `tests/` 目录和 pytest 测试

4. 通过 `python -m todo` 运行

完成后确保 pytest 通过。