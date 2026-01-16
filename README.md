# PPTReviewer

> 自动化房地产数据分析与PPT报告生成系统

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 📖 项目简介

PPTReviewer 是一个基于 Python 的自动化 PPT 报告生成系统，专为房地产行业设计。它能够从 PostgreSQL 数据库中提取房地产交易数据，自动进行数据处理、分析并生成包含图表、表格和智能结论的专业 PPT 报告。

### 核心特性

- 🔄 **自动化数据提取** - 从数据库自动获取和处理房地产数据
- 📊 **多种图表支持** - 柱状图、折线图、表格等多种可视化形式
- 🎨 **完全配置化** - 样式、版式、文案全部通过 YAML 配置
- 🤖 **智能结论生成** - 根据数据自动生成分析结论
- 🌏 **完美中文支持** - 支持中文字体和文本
- 🏗️ **模块化架构** - 清晰的分层设计，易于扩展

---

## 📂 项目结构

```
PPTReviewer/
├── config/                      # 配置文件目录
│   ├── constants.py            # 配色主题定义（22种配色方案）
│   ├── settings.py             # 全局设置
│   └── templates/              # YAML模板配置
│       ├── template_definitions.yaml  # 模板定义
│       ├── layouts.yaml          # 版式配置（元素位置）
│       ├── styles.yaml           # 样式配置（字体、颜色）
│       └── text_pattern.yaml     # 文案模板（Jinja2）
│
├── core/                        # 核心业务层
│   ├── database.py             # 数据库连接管理（单例）
│   ├── dao.py                  # 数据访问对象
│   ├── data_provider.py        # 数据提供者（Facade）
│   ├── transformers.py         # 数据转换器
│   ├── conclusion_generator.py # 结论生成器
│   ├── schemas.py              # Pydantic数据模型
│   ├── ppt_operations.py       # PPT操作核心类
│   ├── resources.py            # 资源管理器（单例）
│   ├── layout_manager.py       # 版式管理器（单例）
│   ├── style_manager.py        # 样式管理器（单例）
│   └── context.py              # 上下文管理
│
├── engine/                      # PPT生成引擎
│   ├── ppt_engine.py           # 引擎主类
│   ├── builder.py              # 配置构建器
│   └── slide_renderers.py      # 渲染器
│
├── utils/                       # 工具模块
│   ├── data_utils.py           # 数据处理工具
│   └── text_parser.py          # Markdown解析
│
├── data/                        # PPT模板文件目录
│   ├── ReSlide_01/             # 板块面积段分布模板
│   ├── ReSlide_02/             # 新房交叉结构分析模板
│   ├── ReSlide_03/             # 二手房交叉结构分析模板
│   └── ReSlide_04/             # 新房市场容量分析模板
│
├── test/                        # 测试文件和数据
├── output/                      # 生成的PPT文件输出目录
├── logs/                        # 日志文件目录
│
├── test_all_templates.py        # 主测试工具
├── diagnose_templates.py        # 模板诊断工具
├── .env                         # 数据库配置
├── pyproject.toml               # 项目配置
└── readme.md                    # 项目说明文档
```

---

## 🚀 快速开始

### 环境要求

- Python >= 3.12
- PostgreSQL 数据库
- 操作系统：Windows/Linux/macOS

### 安装依赖

```bash
# 使用 uv（推荐）
uv sync

# 或使用 pip
pip install -r requirements.txt
```

### 数据库配置

编辑 `.env` 文件，配置数据库连接信息：

```env
SQL_USER=your_username
SQL_PASSWORD=your_password
SQL_HOST=your_host
SQL_PORT=your_port
SQL_DB=RealEstate
```

### 数据表结构

数据库中需要包含以下表：

- `Beijing_new_house` - 北京新房数据
- `Guangzhou_new_house` - 广州新房数据
- `Guangzhou_resale_house` - 广州二手房数据
- `Shenzhen_new_house` - 深圳新房数据
- `Shenzhen_resale_house` - 深圳二手房数据

**表字段说明**：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| dim_area | numeric | 面积维度 |
| dim_price | numeric | 价格维度 |
| supply_sets | integer | 供应套数 |
| trade_sets | integer | 交易套数 |
| city | varchar | 城市 |
| block | varchar | 板块 |
| date_code | varchar | 日期代码 |

---

## 💡 使用方式

### 方式一：使用测试工具（推荐）

运行交互式测试工具：

```bash
python test_all_templates.py
```

选择测试模式：
- **选项1** - 快速测试：每个模板测试一个样本（推荐首次使用）
- **选项2** - 完整测试：所有表、所有板块、所有模板
- **选项3** - 测试特定模板：输入模板ID进行单独测试
- **选项4** - 测试特定表：选择某个表进行完整测试

### 方式二：使用 API

```python
from core import resource_manager
from core.context import PresentationContext
from core.data_provider import RealEstateDataProvider
from engine import PPTGenerationEngine

# 1. 加载所有配置
resource_manager.load_all()

# 2. 准备数据
provider = RealEstateDataProvider(
    city="Beijing",
    block="Liangxiang",
    start_year="2020",
    end_year="2022",
    table_name="Beijing_new_house"
)

# 3. 获取数据（以面积分布为例）
df, conclusion = provider.get_newhouse_area_distribution_with_conclusion(step=20)

# 4. 构建上下文
context = PresentationContext()
context.add_dataset("newhouse_area_dist_data", df)
context.add_variable("Geo_City_Name", "北京")
context.add_variable("Geo_Block_Name", "良乡")
context.add_variable("Temporal_Start_Year", "2020")
context.add_variable("Temporal_End_Year", "2022")
context.add_variables(conclusion)  # 添加结论变量

# 5. 生成PPT
engine = PPTGenerationEngine("output/report.pptx")
engine.generate_multiple_slides([
    {"template_id": "T02_Area_Dist_Bar", "context": context}
])
```

---

## 📊 可用模板

### 当前可用模板

| 模板ID | 说明 | 版式 | 数据需求 |
|--------|------|------|---------|
| `T02_Area_Dist_Bar` | 新房面积分布（柱状图） | 单栏柱状图 | `get_newhouse_area_distribution_with_conclusion()` |
| `T02_Area_Dist_Table` | 新房面积分布（表格） | 单栏表格 | 同上 |
| `T02_Price_Dist_Bar` | 新房价格分布（柱状图） | 单栏柱状图 | `get_newhouse_price_distribution_with_conclusion()` |
| `T02_Price_Dist_Line` | 新房价格分布（折线图） | 单栏折线图 | 同上 |

### 模板系列说明

- **T01系列** - 板块面积段分布（开发中）
- **T02系列** - 新房交叉结构分析（✅ 可用）
- **T03系列** - 二手房交叉结构分析（规划中）
- **T04系列** - 新房市场容量分析（规划中）

---

## 🔧 核心模块说明

### 数据层

```
Database (PostgreSQL)
    ↓
DatabaseManager (单例模式 - 连接管理)
    ↓
RealEstateDAO (SQL执行)
    ↓
StatTransformer (数据转换: 分箱、聚合、重塑)
    ↓
RealEstateDataProvider (Facade模式 - 统一接口)
    ↓
ConclusionGenerator (生成分析结论)
    ↓
PresentationContext (数据容器)
    ↓
PPTGenerationEngine (生成PPT)
```

**关键类**：

- **[core/database.py](core/database.py)** - `DatabaseManager`：数据库连接管理，单例模式
- **[core/dao.py](core/dao.py)** - `RealEstateDAO`：执行SQL查询，返回原始DataFrame
- **[core/transformers.py](core/transformers.py)** - `StatTransformer`：数据清洗、分箱、聚合、透视表转换
- **[core/data_provider.py](core/data_provider.py)** - `RealEstateDataProvider`：对外提供业务方法，协调DAO和Transformer
- **[core/conclusion_generator.py](core/conclusion_generator.py)** - `ConclusionGenerator`：根据数据自动生成分析结论

### 配置层

```
text_pattern.yaml (Jinja2模板)
    ↓
template_definitions.yaml (模板定义)
    ↓
    ├─→ layouts.yaml (位置配置)
    └─→ styles.yaml (样式配置)

ResourceManager (单例模式 - 加载所有配置)
    ↓
LayoutManager (查询版式配置)
StyleManager (查询样式配置)
```

**配置文件说明**：

- **[template_definitions.yaml](config/templates/template_definitions.yaml)** - 模板定义，包含模板ID、主题、版式等映射
- **[layouts.yaml](config/templates/layouts.yaml)** - 版式配置，定义元素位置和尺寸
- **[styles.yaml](config/templates/styles.yaml)** - 样式配置，定义图表配色、字体等
- **[text_pattern.yaml](config/templates/text_pattern.yaml)** - 文案模板，使用Jinja2语法

### PPT生成引擎

```
用户指定 template_id
    ↓
SlideConfigBuilder.build()
    ↓
生成 SlideRenderConfig (Pydantic模型)
    ↓
RendererFactory.get_renderer()
    ↓
BaseSlideRenderer.render()
    ↓
python-pptx 生成最终.pptx文件
```

**关键类**：

- **[engine/ppt_engine.py](engine/ppt_engine.py)** - `PPTGenerationEngine`：引擎主类，管理工作流
- **[engine/builder.py](engine/builder.py)** - `SlideConfigBuilder`：构建渲染配置
- **[engine/slide_renderers.py](engine/slide_renderers.py)** - `BaseSlideRenderer`：执行实际渲染
- **[core/ppt_operations.py](core/ppt_operations.py)** - `PPTOperations`：提供PPT操作接口

---

## 📚 API 参考

### RealEstateDataProvider 方法

| 方法 | 说明 | 返回值 |
|------|------|--------|
| `get_supply_transaction_stats_with_conclusion(area_range_size)` | 供需统计 | (DataFrame, dict) |
| `get_area_price_cross_stats_with_conclusion(area_step, price_step)` | 面积x价格交叉分析 | (DataFrame, dict) |
| `get_newhouse_area_distribution_with_conclusion(step)` | 新房面积分布 | (DataFrame, dict) |
| `get_newhouse_price_distribution_with_conclusion(price_range_size)` | 新房价格分布 | (DataFrame, dict) |

### Context 变量说明

**地理维度**：
- `Geo_City_Name` - 城市名（如"北京"）
- `Geo_Block_Name` - 板块名（如"良乡"）

**时间维度**：
- `Temporal_Start_Year` - 起始年份（如"2020"）
- `Temporal_End_Year` - 结束年份（如"2022"）

**结论变量**（自动生成）：
- `Stat_Core_Area_Segment` - 核心面积段
- `Stat_Upgrade_Area_Segment` - 升级面积段
- 其他根据模板类型变化

---

## 🛠️ 配置扩展指南

### 添加新模板

1. **在 [template_definitions.yaml](config/templates/template_definitions.yaml) 中添加定义**：

```yaml
- uid: "Your_Template_ID"
  theme_key: "Your Theme"
  function_key: "Your Function"
  layout_type: "single_column_bar"
  summary_item: 1
  style_config_id: "marketing_orange_green"
  data_keys:
    chart_main: "your_data_key"
```

2. **在 [text_pattern.yaml](config/templates/text_pattern.yaml) 中添加文案**：

```yaml
Your Theme:
  title: "{{Geo_City_Name}}{{Geo_Block_Name}}..."
  Your Function:
    summaries:
      - "变体1文案..."
      - "变体2文案..."
```

3. **在 DataProvider 中实现对应的数据方法**

### 修改样式

编辑 [styles.yaml](config/templates/styles.yaml)：
- 修改颜色主题（22种配色可选）
- 调整字体大小
- 配置坐标轴样式

### 调整版式

编辑 [layouts.yaml](config/templates/layouts.yaml)：
- 调整元素位置
- 修改尺寸大小
- 配置对齐方式

---

## 🔍 诊断和调试

### 使用诊断工具

```bash
python diagnose_templates.py
```

功能：
- 检查 `text_pattern.yaml` 覆盖率
- 验证 `template_definitions.yaml` 配置
- 测试数据格式
- 单个模板生成测试

### 日志查看

日志文件位置：`logs/test_all_templates.log`

使用 Loguru 进行日志记录，包含详细的错误堆栈信息。

---

## 🏗️ 架构设计

### 设计模式应用

1. **单例模式**：ResourceManager, LayoutManager, StyleManager, DatabaseManager
2. **Facade模式**：RealEstateDataProvider 统一数据访问接口
3. **Builder模式**：SlideConfigBuilder 构建复杂配置
4. **Factory模式**：RendererFactory 创建渲染器
5. **Strategy模式**：不同版式对应不同渲染策略

### 架构优势

- ✅ **高度模块化** - 配置、数据、渲染分离
- ✅ **可扩展性强** - 通过 YAML 配置添加新模板，无需修改代码
- ✅ **类型安全** - 使用 Pydantic 进行数据验证
- ✅ **代码质量** - Pre-commit 钩子确保代码规范
- ✅ **测试友好** - 提供完整的测试和诊断工具

---

## 📦 技术栈

### 核心依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| python-pptx | >=0.6.21 | PPT文件操作 |
| pandas | >=1.3.0 | 数据处理 |
| pptx-ea-font | >=0.0.4 | 中文字体支持 |
| pydantic | >=2.12.4 | 数据验证 |
| jinja2 | >=3.1.6 | 模板引擎 |
| sqlalchemy | >=2.0.45 | 数据库ORM |
| psycopg2-binary | >=2.9.11 | PostgreSQL驱动 |
| loguru | >=0.7.3 | 日志 |
| pyyaml | >=6.0.3 | YAML配置解析 |

### 开发工具

- **ruff** - 代码检查和格式化
- **black** - 代码格式化
- **pre-commit** - Git钩子
- **commitizen** - 提交规范

---

## ❓ 常见问题

**Q1: 如何支持新的城市数据表？**

A: 在数据库中创建表，确保字段结构一致（包含 `dim_area`, `dim_price`, `supply_sets`, `trade_sets`, `city`, `block`, `date_code`），然后在 DataProvider 中使用该表名。

**Q2: 如何修改PPT模板的设计？**

A: 编辑 `data/` 目录下的 `.pptx` 文件，这些是 python-pptx 使用的底板文件。

**Q3: 如何添加新的图表类型？**

A: 在 [PPTOperations](core/ppt_operations.py) 中添加新方法，在 [schemas.py](core/schemas.py) 中定义配置模型。

**Q4: 生成的PPT打开失败怎么办？**

A: 运行 `diagnose_templates.py` 检查配置，或查看 `logs/` 目录下的日志文件排查错误。

**Q5: 如何自定义配色方案？**

A: 在 [constants.py](config/constants.py) 中添加新的配色方案，然后在 [styles.yaml](config/templates/styles.yaml) 中引用。

---

## 🗺️ 开发路线图

### 当前状态
- ✅ T02系列4个模板完全可用
- ⏸️ T01、T03、T04系列待修复或完成

### 计划功能
- [ ] 修复T01系列模板打开问题
- [ ] 完成T03二手房分析模块
- [ ] 完成T04市场容量分析的结论生成器
- [ ] 添加饼图支持
- [ ] 支持自定义PPT模板上传
- [ ] 添加Web界面
- [ ] 支持批量生成报告
- [ ] 添加更多数据可视化类型

---

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'feat: Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

**提交规范**：
- `feat:` - 新功能
- `fix:` - 修复bug
- `refactor:` - 重构
- `docs:` - 文档更新
- `test:` - 测试相关
- `chore:` - 构建/工具链相关

---

## 📞 联系方式

如有问题或建议，欢迎提交 Issue 或联系项目维护者。

---

## 🙏 致谢

感谢以下开源项目：
- [python-pptx](https://github.com/scanny/python-pptx) - PPT文件操作库
- [pandas](https://pandas.pydata.org/) - 数据处理库
- [pydantic](https://github.com/pydantic/pydantic) - 数据验证库
- [Jinja2](https://jinja.palletsprojects.com/) - 模板引擎

---
