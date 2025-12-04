# Company X Python 风格指南

## 简介

本风格指南概述了 Company X 开发的 Python 代码的编码规范。
它基于 **PEP 8**，但进行了一些修改，以解决我们组织内部的特定需求和偏好。

-----

## 关键原则

  * **可读性 (Readability)：** 代码应该易于被所有团队成员理解。
  * **可维护性 (Maintainability)：** 代码应该易于修改和扩展。
  * **一致性 (Consistency)：** 在所有项目中坚持一致的风格，可以改善协作并减少错误。
  * **性能 (Performance)：** 尽管可读性至关重要，但代码也应该高效。
  * **可测试性 (Testability)：** 代码应该容易测试。
  * **可扩展性 (Scalability)：** 代码应该易于扩展到新的需求。
  * **简洁性 (Simplicity)：** 代码应该尽可能简单，但不失可读性，也不过于冗长。

-----

## 对 PEP 8 的偏离 (Deviations from PEP 8)

### 行长度 (Line Length)

  * **最大行长度：** **100 个字符**（而非 PEP 8 的 79 个）。
      * 现代屏幕支持更宽的行，在许多情况下提高了代码可读性。
      * 我们代码库中许多常见的模式，例如长字符串或 URL，通常会超过 79 个字符。

### 缩进 (Indentation)

  * **每级缩进使用 4 个空格。** (PEP 8 推荐)

### 导入 (Imports)

  * **分组导入：**
      * 标准库导入 (Standard library imports)
      * 相关的第三方库导入 (Related third party imports)
      * 本地应用/库特定的导入 (Local application/library specific imports)
  * **绝对导入：** 始终使用**绝对导入**以确保清晰度。
  * **组内导入顺序：** **按字母顺序**排序。

### 命名约定 (Naming Conventions)

| 元素 | 约定 | 示例 |
| :--- | :--- | :--- |
| **变量** (Variables) | 小写字母加下划线 (snake\_case) | `user_name`, `total_count` |
| **常量** (Constants) | 大写字母加下划线 | `MAX_VALUE`, `DATABASE_NAME` |
| **函数** (Functions) | 小写字母加下划线 (snake\_case) | `calculate_total()`, `process_data()` |
| **类** (Classes) | 驼峰式命名法 (CapWords/CamelCase) | `UserManager`, `PaymentProcessor` |
| **模块** (Modules) | 小写字母加下划线 (snake\_case) | `user_utils`, `payment_gateway` |

### 文档字符串 (Docstrings)

  * **所有文档字符串使用三重双引号**（`"""Docstring goes here."""`）。
  * **第一行：** 对象用途的简洁摘要。
  * **对于复杂的函数/类：** 包含参数、返回值、属性和异常的详细描述。
  * **使用 Google 风格的文档字符串：** 这有助于自动化文档生成。
    ```python
    def my_function(param1, param2):
        """Single-line summary.
        More detailed description, if necessary.

        Args:
            param1 (int): The first parameter.
            param2 (str): The second parameter.

        Returns:
            bool: The return value. True for success, False otherwise.

        Raises:
            ValueError: If `param2` is invalid.
        """
        # function body here
    ```

### 类型提示 (Type Hints)

  * **使用类型提示：** 类型提示提高了代码可读性，并有助于及早发现错误。
  * **遵循 PEP 484：** 使用标准的类型提示语法。

### 注释 (Comments)

  * **编写清晰简洁的注释：** 解释代码背后的“**原因**”，而不仅仅是“**内容**”。
  * **酌情使用注释：** 编写良好的代码应在可能的情况下**自我解释**。
  * **使用完整的句子：** 注释以大写字母开头并使用正确的标点符号。

### 日志记录 (Logging)

  * **使用标准的日志记录框架：** Company X 使用 `loguru` 模块。
  * **在适当的级别记录：** DEBUG, INFO, WARNING, ERROR, CRITICAL
  * **提供上下文：** 在日志消息中包含相关信息以帮助调试。

### 错误处理 (Error Handling)

  * **使用特定的异常：** 避免使用像 `Exception` 这样宽泛的异常。
  * **优雅地处理异常：** 提供信息丰富的错误消息，避免程序崩溃。
  * **使用 `try...except` 块：** 隔离可能引发异常的代码。

-----

## 工具 (Tooling)

  * **代码格式化工具：** [`ruff`] - 自动强制执行一致的格式。
  * **Linter（代码检查工具）：** [`flake8`] - 识别潜在问题和风格违规。

-----

## 示例 (Example)

```python
"""Module for user authentication."""

import hashlib
import logging
import os

from companyx.db import user_database

LOGGER = logging.getLogger(__name__)

def hash_password(password: str) -> str:
    """Hashes a password using SHA-256.

    Args:
       password (str): The password to hash.

    Returns:
      str: The hashed password.
    """
    salt = os.urandom(16)
    salted_password = salt + password.encode('utf-8')
    hashed_password = hashlib.sha256(salted_password).hexdigest()
    return f"{salt.hex()}:{hashed_password}"

def authenticate_user(username: str, password: str) -> bool:
    """Authenticates a user against the database.

    Args:
        username (str): The user's username.
        password (str): The user's password.

    Returns:
        bool: True if the user is authenticated, False otherwise.
    """
    try:
        user = user_database.get_user(username)
        if user is None:
            LOGGER.warning("Authentication failed: user not found - %s", username)
            return False

        stored_hash = user.password_hash
        salt, hashed_password = stored_hash.split(':')
        salted_password = bytes.fromhex(salt) + password.encode('utf-8')
        calculated_hash = hashlib.sha256(salted_password).hexdigest()

        if calculated_hash == hashed_password:
            LOGGER.info("User authentication successful - %s", username)
            return True
        else:
            LOGGER.warning("Authentication failed: password incorrect - %s", username)
            return False
    except Exception as e:
        # Note: in a real-world application, it's recommended to catch more specific exceptions.
        LOGGER.error("Error during authentication: %s", e)
        return False
```
