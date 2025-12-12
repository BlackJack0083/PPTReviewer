# test_new_system.py
from core import resource_manager
from core.context import PresentationContext
from core.data_provider import RealEstateDataProvider
from engine import PPTGenerationEngine


def run_report_generation():
    resource_manager.load_all()
    # 1. 设定参数
    city = "Beijing"
    block = "Liangxiang"
    start_year = "2020"
    end_year = "2022"
    table_name = "Beijing_new_house"

    # 2. 初始化数据提供者 (连接数据库)
    provider = RealEstateDataProvider(city, block, start_year, end_year, table_name)

    context = PresentationContext()

    # 3. 添加文本变量 (用于替换 PPT 里的 {Geo_City_Name} 等)
    context.add_variable("Geo_City_Name", city)
    context.add_variable("Geo_Block_Name", block)
    context.add_variable("Temporal_Start_Year", start_year)
    context.add_variable("Temporal_End_Year", end_year)

    # 这里的结论性文字变量，理想情况下应该由 Provider 计算得出，这里先写死占位
    context.add_variable("Seg_SupplyDemand_Core_Area", "80-100")
    context.add_variable("Seg_SupplyDemand_Upgrade_Area", "140-160")

    # 4. 获取数据并注入 (替代了 execute_analysis 的功能)

    # 任务 1: 供需柱状图 (SQL 模板 1)
    # 我们直接调用封装好的方法，而不是传 sql 字符串
    df_supply_trans = provider.get_supply_transaction_stats(area_range_size=20)
    context.add_dataset("supply_trans_data", df_supply_trans)

    # 任务 2: 面积x价格 交叉表 (SQL 模板 2)
    df_cross = provider.get_area_price_cross_stats(area_step=20, price_step=1)
    context.add_dataset("cross_analysis_data", df_cross)

    # # 任务 3: 面积分布 (SQL 模板 3)
    # df_area_dist = provider.get_segment_distribution('dim_area', step=20, unit='m²')
    # context.add_dataset("area_dist_data", df_area_dist)

    # 5. 生成 PPT
    engine = PPTGenerationEngine("output/db_report.pptx")

    tasks = [
        # 这里的 template_id 必须对应 template_definitions.yaml 里的 uid
        # 且 data_keys 必须对应上面 add_dataset 的 key
        {"template_id": "T01_Supply_Trans_Bar", "context": context},
        # {"template_id": "T02_Cross_Analysis", "context": context}, # 示例
    ]
    engine.generate_multiple_slides(tasks)


if __name__ == "__main__":
    run_report_generation()
