import os
import tempfile

# 必须在导入 app.* 之前：app.database 按 settings.database_url 创建模块级 engine。
# 测试用 SQLite，不依赖 Postgres；各用例再通过 dependency_overrides 注入内存库。
_fd, _path = tempfile.mkstemp(suffix=".db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_path}")
os.environ.setdefault("SEED_ON_EMPTY", "false")
