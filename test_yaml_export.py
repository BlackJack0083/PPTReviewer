#!/usr/bin/env python3
"""
测试 YAML 导出功能
"""
from pathlib import Path

from core import ContextBuilder, resource_manager
from core.data_provider import RealEstateDataProvider
from engine import PPTGenerationEngine

# 配置
city = "Beijing"
block = "Beiqijia"
start_year = "2020"
end_year = "2022"
table = "Beijing_new_house"

# 测试单个模板
template_id = "T02_Double_Price_Dist_Line"

# 加载资源
resource_manager.load_all()

# 获取模板元数据
template_meta = resource_manager.get_template(template_id)

# 初始化 Provider
provider = RealEstateDataProvider(city, block, start_year, end_year, table)

# 构建 Context
context = ContextBuilder.build_context(
    template_meta=template_meta,
    provider=provider,
    city=city,
    block=block,
    start_year=start_year,
    end_year=end_year,
)

# 生成 PPT（会自动导出 YAML）
output_file = f"output/test_yaml_export/{template_id}.pptx"
Path(output_file).parent.mkdir(parents=True, exist_ok=True)

engine = PPTGenerationEngine(output_file)
engine.generate_multiple_slides(
    [{"template_id": template_id, "context": context}]
)

print(f"\n✓ PPT 和 YAML 已生成")
print(f"  PPT: {output_file}")
print(f"  YAML: {output_file.replace('.pptx', '')}*.yaml")
