
# Remote Conda Decorator

一个重量级 Python 工具，通过 `@wrap` 装饰器让函数无缝在指定的 Conda 虚拟环境中执行。专为数据科学优化，支持 Jupyter Notebook 及 **AnnData 零拷贝传输**。

## ✨ 特性

- **环境穿梭**：本地定义函数，远程环境执行。
- **Notebook 友好**：支持交互式定义的函数 (基于 `dill`)。
- **极速传输**：
  - 普通参数：内存文件交换。
  - **AnnData**：利用 `/dev/shm` 实现零拷贝传输，无序列化开销。
- **自动注入**：自动处理类定义与 `sys.path`，避免跨进程兼容性报错。

## 📦 安装与依赖

1. **系统要求**：Linux (依赖 `/dev/shm`)。
2. **复制文件**：将 `remote_conda_decorator.py` 放入项目目录。
3. **安装依赖**：**本地**和**目标环境**都需安装 `dill`。

