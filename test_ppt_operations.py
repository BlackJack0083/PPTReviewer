"""
PPT操作API测试脚本
测试所有的PPT操作功能
"""

import os
import pandas as pd
from ppt_operations import create_slide, add_title, add_content, add_table


def test_ppt_operations():
    """测试所有PPT操作功能"""

    # 创建输出目录
    output_dir = "./test_output"
    os.makedirs(output_dir, exist_ok=True)

    # 测试参数
    ppt_name = "测试演示文稿"
    page_num = 3
    slide_width = 25.4  # 标准宽度（厘米）
    slide_height = 19.05  # 标准高度（厘米）
    ppt_script = os.path.join(output_dir, "test_presentation.pptx")

    print("=== 开始测试PPT操作API ===\n")

    # 1. 测试创建PPT
    print("1. 测试创建PPT...")
    try:
        create_slide(ppt_name, page_num, slide_width, slide_height, ppt_script)
        print("✓ PPT创建成功\n")
    except Exception as e:
        print(f"✗ PPT创建失败: {e}\n")
        return

    # 2. 测试添加标题
    print("2. 测试添加标题...")
    try:
        title_content = {
            'text': '测试标题',
            'font_size': 24,
            'font_bold': True,
            'font_name': '微软雅黑',  # 使用更常见的字体
            'font_color': '黑色'
        }

        title_layout = {
            'left': 2.0,
            'top': 1.0,
            'width': 15.0,
            'height': 2.0,
            'alignment': '居中',
            'word_wrap': True
        }

        add_title(ppt_script, 1, title_content, title_layout)
        print("✓ 标题添加成功\n")
    except Exception as e:
        print(f"✗ 标题添加失败: {e}\n")

    # 3. 测试添加内容
    print("3. 测试添加内容...")
    try:
        content_text = {
            'text': '这是一个测试内容文本框。用于验证文本内容添加功能是否正常工作。支持中文内容和基本的文本格式设置。',
            'font_size': 14,
            'font_bold': False,
            'font_name': '微软雅黑',
            'font_color': '黑色'
        }

        content_layout = {
            'left': 2.0,
            'top': 4.0,
            'width': 20.0,
            'height': 5.0,
            'alignment': '左对齐',
            'word_wrap': True
        }

        add_content(ppt_script, 1, content_text, content_layout)
        print("✓ 内容添加成功\n")
    except Exception as e:
        print(f"✗ 内容添加失败: {e}\n")

    # 4. 测试添加表格
    print("4. 测试添加表格...")
    try:
        # 创建测试数据
        test_data = pd.DataFrame({
            '姓名': ['张三', '李四', '王五', '赵六'],
            '年龄': [25, 30, 28, 35],
            '部门': ['技术部', '销售部', '人事部', '财务部'],
            '工资': [8000, 7500, 6500, 9000]
        })

        table_layout = {
            'left': 1.0,
            'top': 10.0,
            'width': 23.0,
            'height': 6.0
        }

        add_table(ppt_script, 1, table_layout, test_data, '微软雅黑', 10)
        print("✓ 表格添加成功\n")
    except Exception as e:
        print(f"✗ 表格添加失败: {e}\n")

    # 5. 测试多页面操作
    print("5. 测试多页面操作...")
    try:
        # 在第二页添加标题和内容
        title2_content = {
            'text': '第二页标题',
            'font_size': 22,
            'font_bold': True,
            'font_name': '微软雅黑',
            'font_color': '蓝色'
        }

        title2_layout = {
            'left': 3.0,
            'top': 2.0,
            'width': 15.0,
            'height': 2.0,
            'alignment': '居中',
            'word_wrap': True
        }

        add_title(ppt_script, 2, title2_content, title2_layout)

        content2_text = {
            'text': '这是第二页的内容。用于验证多页面操作功能。',
            'font_size': 16,
            'font_bold': False,
            'font_name': '微软雅黑',
            'font_color': '黑色'
        }

        content2_layout = {
            'left': 2.0,
            'top': 5.0,
            'width': 20.0,
            'height': 8.0,
            'alignment': '左对齐',
            'word_wrap': True
        }

        add_content(ppt_script, 2, content2_text, content2_layout)
        print("✓ 多页面操作成功\n")
    except Exception as e:
        print(f"✗ 多页面操作失败: {e}\n")

    # 6. 测试在第三页添加另一个表格
    print("6. 测试在第三页添加表格...")
    try:
        # 创建不同的测试数据
        sales_data = pd.DataFrame({
            '产品': ['产品A', '产品B', '产品C', '产品D', '产品E'],
            'Q1销量': [100, 150, 200, 120, 180],
            'Q2销量': [110, 160, 180, 140, 200],
            'Q3销量': [120, 170, 220, 160, 210],
            'Q4销量': [130, 180, 240, 180, 230]
        })

        table2_layout = {
            'left': 2.0,
            'top': 3.0,
            'width': 20.0,
            'height': 10.0
        }

        add_table(ppt_script, 3, table2_layout, sales_data, '微软雅黑', 8)
        print("✓ 第三页表格添加成功\n")
    except Exception as e:
        print(f"✗ 第三页表格添加失败: {e}\n")

    print("=== 测试完成 ===")
    print(f"测试PPT文件已生成: {ppt_script}")
    print("请检查生成的PPT文件以验证所有功能是否正常工作。")

    return ppt_script


def test_error_handling():
    """测试错误处理"""
    print("\n=== 测试错误处理 ===\n")

    output_dir = "./test_output"
    ppt_script = os.path.join(output_dir, "test_presentation.pptx")

    # 测试无效页码
    print("1. 测试无效页码...")
    try:
        content = {'text': '测试', 'font_size': 14}
        layout = {'left': 1, 'top': 1, 'width': 10, 'height': 2, 'alignment': '左对齐', 'word_wrap': True}
        add_title(ppt_script, 999, content, layout)  # 无效页码
        print("✗ 应该抛出错误但没有")
    except ValueError as e:
        print(f"✓ 正确捕获无效页码错误: {e}")
    except Exception as e:
        print(f"✗ 捕获了意外错误: {e}")

    # 测试不存在的文件
    print("\n2. 测试不存在的文件...")
    try:
        non_existent_file = os.path.join(output_dir, "non_existent.pptx")
        content = {'text': '测试', 'font_size': 14}
        layout = {'left': 1, 'top': 1, 'width': 10, 'height': 2, 'alignment': '左对齐', 'word_wrap': True}
        add_title(non_existent_file, 1, content, layout)
        print("✗ 应该抛出错误但没有")
    except Exception as e:
        print(f"✓ 正确捕获文件不存在错误: {e}")


if __name__ == "__main__":
    # 运行主要功能测试
    ppt_file = test_ppt_operations()

    # 运行错误处理测试
    test_error_handling()

    print(f"\n所有测试完成！生成的PPT文件: {ppt_file}")