from engine.yaml_importer import rebuild_ppt_from_yaml

yaml_path = 'output/mass_production/beijing/Beiguan_-_Luyuan/BeijingBeiguan-Luyuan-T02_Double_Price_Dist_Line-5407dca8879d4c56.yaml'
output_path = 'output/test_rebuild3.pptx'

rebuild_ppt_from_yaml(yaml_path, output_path)
print(f'PPT generated: {output_path}')